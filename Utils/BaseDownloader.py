__author__ = 'Prudhvi PLN'

import logging
import os
import requests
import sys
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from shutil import rmtree
from ssl import _create_unverified_context
from tqdm.auto import tqdm

from Utils.commons import colprint, exec_os_cmd, retry, PRINT_THEMES, DISPLAY_COLORS


class BaseDownloader():
    '''
    Download Client for downloading files directly using requests and http.client
    '''
    def __init__(self, dl_config, ep_details, session=None):
        # logger init
        self.logger = logging.getLogger()
        # set downloader configuration
        self.out_file = ep_details['episodeName']
        self.out_dir = dl_config['download_dir']
        # add extra folder for season
        if ep_details.get('type', '') == 'tv':
            self.out_dir = f"{self.out_dir}{os.sep}Season-{ep_details['season']}"
        self.concurrency = None if dl_config.get('concurrency_per_file', 'auto') == 'auto' else dl_config['concurrency_per_file']
        self.parent_temp_dir = os.path.join(f'{self.out_dir}', 'temp_dir') if dl_config.get('temp_download_dir', 'auto') == 'auto' else dl_config['temp_download_dir']
        self.temp_dir = os.path.join(f"{self.parent_temp_dir}", f"{self.out_file.replace('.mp4','')}") #create temp directory per episode
        self.request_timeout = dl_config.get('request_timeout', 30)
        self.series_type = ep_details.get('type', 'series')
        self.subtitles = ep_details.get('subtitles', {})
        # special case for encrypted subtitles in kisskh client
        self.encrypted_subs_details = ep_details.get('encrypted_subs_details', {})
        self.thread_name_prefix = 'udb-mp4-'

        # create a requests session and use across to re-use cookies
        self.req_session = session if session else requests.Session()

        # set http client usage based on config. As on Feb 21 2025, kisskh works with only http.client
        self.use_http_client = dl_config.get('use_http_client', False)

        self.req_session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept-Encoding": "*",
            "Connection": "keep-alive"
        }
        # update referer if defined
        if ep_details.get('refererLink'): self.req_session.headers.update({"Referer": ep_details['refererLink']})

    def _colprint(self, theme, text, **kwargs):
        '''
        Wrapper for color printer function
        '''
        if 'input' in theme:
            return colprint(theme, text, **kwargs)
        else:
            colprint(theme, text, **kwargs)

    def _get_raw_stream_data(self, url, stream=True, header=None):
        '''
        Fetch raw stream data using requests or http.client
        '''
        if self.use_http_client:
            # Use http.client for the request with redirect support
            max_redirects = 5
            current_url = url
            for _ in range(max_redirects):
                parsed_url = requests.utils.urlparse(current_url)
                conn = http.client.HTTPSConnection(parsed_url.netloc, timeout=self.request_timeout, context=_create_unverified_context())
                path = parsed_url.path
                if parsed_url.query:
                    path += '?' + parsed_url.query
                headers = self.req_session.headers.copy()
                if header: headers.update(header)
                conn.request("GET", path, headers=headers)
                response = conn.getresponse()
                if response.status in [200, 206]:  # Success - 206 means partial data (i.e., for chunked downloads)
                    return response
                elif response.status in [301, 302, 303, 307, 308]:
                    # Handle redirect
                    location = response.getheader('Location')
                    if not location:
                        raise Exception(f'Redirect ({response.status}) with no Location header')
                    current_url = requests.compat.urljoin(current_url, location)
                    conn.close()
                    continue
                else:
                    raise Exception(f'Failed with response code: {response.status}')
            raise Exception(f'Too many redirects while fetching {url}')
        else:
            # Use requests for the request
            headers = self.req_session.headers.copy()
            if header: headers.update(header)
            response = self.req_session.get(url, stream=stream, timeout=self.request_timeout, headers=headers)
            if response.status_code in [200, 206]:  # 206 means partial data (i.e., for chunked downloads)
                return response
            else:
                raise Exception(f'Failed with response code: {response.status_code}')

    def _get_stream_data(self, url, to_text=False, stream=False):
        response = self._get_raw_stream_data(url, stream)
        if self.use_http_client:
            data = response.read()
            return data.decode('utf-8') if to_text else data
        else:
            return response.text if to_text else response.content

    def _create_out_dirs(self):
        self.logger.debug(f'Creating output directories: {self.out_dir}')
        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _remove_out_dirs(self):
        rmtree(self.temp_dir)

    def _cleanup_out_dirs(self):
        if len(os.listdir(self.parent_temp_dir)) == 0: os.rmdir(self.parent_temp_dir)
        if len(os.listdir(self.out_dir)) == 0: os.rmdir(self.out_dir)

    def _exec_cmd(self, cmd):
        self.logger.debug(f'Executing system command: {cmd}')
        return exec_os_cmd(cmd)

    def _get_display_prefix(self):
        # shorten the name to show only ep number
        try:
            # set display prefix based on series type if defined
            if self.series_type.lower() == 'tv':
                ss_no = self.out_dir.split('-')[-1]
                ep_no = self.out_file.split()[1]
                return f'S{int(ss_no):02d}E{int(ep_no):02d}'
            elif self.series_type.lower() == 'movie':
                return 'Movie'

            ep_no = self.out_file.split()[-3]

            try:
                display_prefix = f'Episode-{int(ep_no):02d}'
            except ValueError as ve:
                display_prefix = f'Movie' if ep_no.lower() == 'movie' else f'Episode-{ep_no}'

        except:
            display_prefix = 'Movie'

        return display_prefix

    def _create_chunk_header(self, start):
        end = start + self.chunk_size - 1
        return {'Range': f'bytes={start}-{end}'}

    @retry()
    def _download_chunk(self, chunk_details):
        '''
        download chunk file from download link based on defined chunk size. Reuse if already downloaded.

        Returns: (download_status, progress_bar_increment)
        '''
        try:
            dl_link, chunk_header, chunk_name = chunk_details
            chunk_file = os.path.join(f'{self.temp_dir}', f'{chunk_name}')

            # check if the chunk is already downloaded
            if os.path.isfile(chunk_file) and os.path.getsize(chunk_file) > 0:
                return (f'Chunk [{chunk_name}] already exists. Reusing.', os.path.getsize(chunk_file))

            # get the data for the chunk size defined in the header
            response = self._get_raw_stream_data(dl_link, False, chunk_header)

            # capture the size to update progress bar
            size = 0 
            with open(chunk_file, 'wb') as f:
                if isinstance(response, http.client.HTTPResponse):
                    while True:
                        chunk = response.read(self.chunk_size)
                        if not chunk:
                            break
                        size += f.write(chunk)
                else:
                    for chunk in response.iter_content(self.chunk_size):
                        if chunk:
                            size += f.write(chunk)

            return (f'Chunk [{chunk_name}] downloaded', size)

        except Exception as e:
            return (f'\nERROR: Chunk download failed [{chunk_name}] due to: {e}', 0)

    def _multi_threaded_download(self, download_func, urls, **metadata):
        reused_segments = 0
        failed_segments = 0
        ep_no = self._get_display_prefix()
        type = metadata.pop('type')
        self.logger.debug(f'[{ep_no}] Downloading {len(urls)} {type} using {self.concurrency} workers...')

        theme = PRINT_THEMES['results'] if DISPLAY_COLORS else ''
        metadata.update({
            'desc': f'Downloading {ep_no}',
            'file': sys.stdout,
            'ascii': '░▒█',
            'leave': True,
            'bar_format': theme + '{l_bar}{bar}' + theme + '{r_bar}'
        })

        # show progress of download using tqdm
        with tqdm(**metadata) as progress:
            # parallelize download of segments/chunks using a threadpool
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=self.thread_name_prefix) as executor:
                results = [ executor.submit(download_func, ts_url) for ts_url in urls ]

                for result in as_completed(results):
                    status, size = result.result()
                    if 'ERROR' in status:
                        self._colprint('error', status)
                        failed_segments += 1
                    elif 'Reusing' in status:
                        reused_segments += 1
                        # update status only if segment is downloaded
                        progress.update(size)
                    else:
                        progress.update(size)

                    # add reused / failed segments/chunks status
                    seg_status = f'R/F: {reused_segments}/{failed_segments}'
                    progress.set_postfix_str(seg_status, refresh=True)

        self.logger.info(f'[{ep_no}] {type.capitalize()} download status: Total: {len(urls)} | Reused: {reused_segments} | Failed: {failed_segments}')
        if failed_segments > 0:
            raise Exception(f'Failed to download {failed_segments} / {len(urls)} {type}')

    def _merge_chunks(self, chunks_count):
        out_file = os.path.join(f'{self.out_dir}', f'{self.out_file}')

        with open(out_file, 'wb') as outfile:
            # iterate through the downloaded chunks
            for chunk_no in range(chunks_count):
                chunk_file = os.path.join(f"{self.temp_dir}", f"{self.out_file}.chunk{chunk_no}")
                # write the chunks to a single file
                with open(chunk_file, 'rb') as s:
                    outfile.write(s.read())
                # remove the merged chunk
                os.remove(chunk_file)

    def _download_subtitles(self):
        for sub_name in list(self.subtitles):
            sub_link = self.subtitles[sub_name]
            sub_file = os.path.join(self.temp_dir, sub_name.replace(' ', '_') + '_' + os.path.basename(sub_link.split('?')[0]))
            # update the dictionary pointing to downloaded file
            self.subtitles[sub_name] = sub_file

            try:
                self.logger.debug(f'Downloading {sub_name} subtitle from {sub_link} to {sub_file}')
                if os.path.isfile(sub_file):
                    self.logger.debug('Subtitle file already exists. Skipping...')
                    continue
                sub_content = self._get_stream_data(sub_link)
                # download the subtitle to local
                with open(sub_file, 'wb') as f:
                    f.write(sub_content)

                if self.encrypted_subs_details.get(sub_name):
                    self._decrypt_subtitle_file(sub_file, **self.encrypted_subs_details[sub_name])

            except Exception as e:
                self.logger.warning(f'Failed to download {sub_name} subtitle with error: {e}')
                self.subtitles.pop(sub_name)

    def _decrypt_subtitle_file(self, sub_file, **kwargs):
        self.logger.debug(f'Decrypting subtitle file: {sub_file}')
        decrypter = kwargs['decrypter']
        subs_key, subs_iv = kwargs['key'], kwargs['iv']

        with open(sub_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        decryption_fail_count = 0
        total_line_count = 0
        with open(sub_file, 'w', encoding='utf-8') as file:
            for line in lines:
                if line.strip() and not line.strip().isdigit() and "-->" not in line:
                    try:
                        # decrypt and replace subtitle text lines
                        file.write(decrypter(line.strip(), subs_key, subs_iv) + '\n')
                        total_line_count += 1
                    except:
                        # write the line as-is if decryption fails
                        file.write(line)
                        decryption_fail_count += 1
                else:
                    # write sequence numbers, timestamps, and empty lines as-is
                    file.write(line)
        if decryption_fail_count > 0:
            self.logger.warning(f'Failed to decrypt {decryption_fail_count}/{total_line_count} lines in the subtitle file')

    def _add_subtitles(self):
        # print(f'Converting {self.out_file} to mp4')
        out_file = os.path.join(f'{self.out_dir}', f'{self.out_file}')
        # ffmpeg can't do in-place conversion. So, create a temp file and replace the original file
        temp_out_file = os.path.join(f'{self.out_dir}', f'temp_{self.out_file}')
        command = [f'ffmpeg -loglevel warning -i "{out_file}"']
        maps = ['-map 0:v -map 0:a'] if self.subtitles else []
        metadata = []

        # Prepare the command if subtitles are present
        for i, (lang, url) in enumerate(self.subtitles.items(), start=1):
            command.append(f'-i "{url}"')
            maps.append(f'-map {i}')
            metadata.append(f'-metadata:s:s:{i-1} title="{lang}"')

        metadata.append(f'-c:v copy -c:a copy -c:s mov_text -bsf:a aac_adtstoasc "{temp_out_file}"')

        cmd = ' '.join(command + maps + metadata)
        self._exec_cmd(cmd)

        # Replace original file with the new file
        os.replace(temp_out_file, out_file)

    def start_download(self, dl_link):
        # set chunk size to 1MiB
        self.chunk_size = 1024*1024
        # create output directory
        self._create_out_dirs()

        self.logger.debug('Fetching stream data')
        dl_data = self._get_raw_stream_data(dl_link, True)
        file_size = int(dl_data.headers.get('content-length', 0))

        chunks = range(0, file_size, self.chunk_size)
        chunk_urls = [[dl_link, self._create_chunk_header(chunk), f'{self.out_file}.chunk{chunk_no}'] for chunk_no, chunk in enumerate(chunks)] 

        self.logger.debug('Downloading chunks')
        metadata = {
            'type': 'chunks',
            'total': file_size,
            'unit': 'iB',
            'unit_scale': True,
            'unit_divisor': 1024
        }
        self._multi_threaded_download(self._download_chunk, chunk_urls, **metadata)

        self.logger.debug('Merging chunks to single file')
        self._merge_chunks(len(chunks))

        if self.subtitles:
            self.logger.debug('Downloading subtitles')
            self._download_subtitles()
            self.logger.debug('Adding subtitles to the video')
            self._add_subtitles()

        # remove temp dir once completed and dir is empty
        self.logger.debug('Removing temporary directories')
        self._remove_out_dirs()

        return (0, None)