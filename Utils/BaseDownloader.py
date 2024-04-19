__author__ = 'Prudhvi PLN'

import logging
import os
import requests
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from shutil import rmtree
from tqdm.auto import tqdm
from urllib3.util.retry import Retry

from Utils.commons import colprint, exec_os_cmd, retry, PRINT_THEMES, DISPLAY_COLORS


class BaseDownloader():
    '''
    Download Client for downloading files directly using requests
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
        self.concurrency = dl_config['concurrency_per_file'] if dl_config['concurrency_per_file'] != 'auto' else None
        self.parent_temp_dir = dl_config['temp_download_dir'] if dl_config['temp_download_dir'] != 'auto' else os.path.join(f'{self.out_dir}', 'temp_dir')
        self.temp_dir = os.path.join(f"{self.parent_temp_dir}", f"{self.out_file.replace('.mp4','')}") #create temp directory per episode
        self.request_timeout = dl_config['request_timeout']
        self.series_type = ep_details.get('type', 'series')
        self.subtitles = ep_details.get('subtitles', {})
        self.referer = ep_details['refererLink']
        self.thread_name_prefix = 'udb-mp4-'

        # create a requests session and use across to re-use cookies
        self.req_session = session if session else requests.Session()
        # add retries with backoff
        retry = Retry(total=3, backoff_factor=0.1)
        adapter = HTTPAdapter(max_retries=retry)
        self.req_session.mount('http://', adapter)
        self.req_session.mount('https://', adapter)
        # disable insecure warnings
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        self.req_session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept-Encoding": "*",
            "Connection": "keep-alive",
            "Referer": self.referer
        }

    def _colprint(self, theme, text, **kwargs):
        '''
        Wrapper for color printer function
        '''
        if 'input' in theme:
            return colprint(theme, text, **kwargs)
        else:
            colprint(theme, text, **kwargs)

    def _get_raw_stream_data(self, url, stream=True, header=None):
        # print(f'{self.req_session}: {url}')
        if header is not None:
            response = self.req_session.get(url, verify=False, stream=stream, timeout=self.request_timeout, headers=header)
        else:
            response = self.req_session.get(url, verify=False, stream=stream, timeout=self.request_timeout)
        # print(response)

        if response.status_code in [200, 206]:  # 206 means partial data (i.e., for chunked downloads)
            return response
        else:
            raise Exception(f'Failed with response code: {response.status_code}')

    def _get_stream_data(self, url, to_text=False, stream=False):
        response = self._get_raw_stream_data(url, stream)
        return response.text if to_text else response.content

    def _create_out_dirs(self):
        self.logger.debug(f'Creating outout directories: {self.out_dir}')
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
            if self.series_type == 'tv':
                ss_no = self.out_dir.split('-')[-1]
                ep_no = self.out_file.split()[1]
                return f'S{int(ss_no):02d}E{int(ep_no):02d}'
            elif self.series_type == 'movie':
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

        # remove temp dir once completed and dir is empty
        self.logger.debug('Removing temporary directories')
        self._remove_out_dirs()

        return (0, None)
