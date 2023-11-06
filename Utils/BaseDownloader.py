__author__ = 'Prudhvi PLN'

import logging
import os
import requests
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from subprocess import Popen, PIPE
from tqdm.auto import tqdm
from urllib3.util.retry import Retry

from Utils.commons import retry


class BaseDownloader():
    '''Download Client for downloading files directly using requests'''

    def __init__(self, dl_config, referer_link, out_file, session=None):
        # logger init
        self.logger = logging.getLogger()
        # set downloader configuration
        self.out_dir = dl_config['download_dir']
        self.concurrency = dl_config['concurrency_per_file'] if dl_config['concurrency_per_file'] != 'auto' else None
        self.parent_temp_dir = dl_config['temp_download_dir'] if dl_config['temp_download_dir'] != 'auto' else os.path.join(f'{self.out_dir}', 'temp_dir')
        self.temp_dir = os.path.join(f"{self.parent_temp_dir}", f"{out_file.replace('.mp4','')}") #create temp directory per episode
        self.request_timeout = dl_config['request_timeout']
        self.referer = referer_link
        self.out_file = out_file
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
        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _remove_out_dirs(self):
        shutil.rmtree(self.temp_dir)

    def _cleanup_out_dirs(self):
        if len(os.listdir(self.parent_temp_dir)) == 0: os.rmdir(self.parent_temp_dir)
        if len(os.listdir(self.out_dir)) == 0: os.rmdir(self.out_dir)

    def _exec_cmd(self, cmd):
        self.logger.debug(f'Executing command: {cmd}')
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
        # print stdout to console
        msg = proc.communicate()[0].decode("utf-8")
        std_err = proc.communicate()[1].decode("utf-8")
        rc = proc.returncode
        if rc != 0:
            raise Exception(f"Error occured: {std_err}")
        return msg

    def _get_shortened_ep_name(self):
        # shorten the name to show only ep number
        try:
            ep_no = self.out_file.split()[-3]
            try:
                ep_no = f'Epsiode-{int(ep_no):02d}'
            except ValueError as ve:
                ep_no = f'Movie' if ep_no.lower() == 'movie' else f'Epsiode-{ep_no}'
        except:
            ep_no = f'Movie'

        return ep_no

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
        ep_no = self._get_shortened_ep_name()
        type = metadata.pop('type')
        self.logger.debug(f'[{ep_no}] Downloading {len(urls)} {type} using {self.concurrency} workers...')

        metadata.update({
            'desc': f'Downloading {ep_no}',
            'file': sys.stdout,
            'colour': 'green',
            'ascii': '░▒█',
            'leave': True
        })

        # show progress of download using tqdm
        with tqdm(**metadata) as progress:
            # parallelize download of segments/chunks using a threadpool
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=self.thread_name_prefix) as executor:
                results = [ executor.submit(download_func, ts_url) for ts_url in urls ]

                for result in as_completed(results):
                    status, size = result.result()
                    if 'ERROR' in status:
                        print(status)
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
        self.logger.debug('Creating output directories')
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
