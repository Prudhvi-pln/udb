__author__ = 'Prudhvi PLN'

import os
import re
import requests
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from requests.adapters import HTTPAdapter
from subprocess import Popen, PIPE
from time import time
from tqdm.auto import tqdm
from urllib3.util.retry import Retry

from Utils.commons import retry

debug = False

class HLSDownloader():
    # References: https://github.com/Oshan96/monkey-dl/blob/master/anime_downloader/util/hls_downloader.py
    # https://github.com/josephcappadona/m3u8downloader/blob/master/m3u8downloader/m3u8.py

    def __init__(self, dl_config, referer_link, out_file, session=None):
        self.out_dir = dl_config['download_dir']
        self.parent_temp_dir = dl_config['temp_download_dir'] if dl_config['temp_download_dir'] != 'auto' else os.path.join(f'{self.out_dir}', 'temp_dir')
        self.temp_dir = os.path.join(f"{self.parent_temp_dir}", f"{out_file.replace('.mp4','')}") #create temp directory per episode
        self.concurrency = dl_config['concurrency_per_file'] if dl_config['concurrency_per_file'] != 'auto' else None
        self.request_timeout = dl_config['request_timeout']
        self.referer = referer_link
        self.out_file = out_file
        self.m3u8_file = os.path.join(f'{self.temp_dir}', 'uwu.m3u8')
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

    def _get_stream_data(self, url, to_text=False):
        # print(f'{self.req_session}: {url}')
        response = self.req_session.get(url, verify=False, timeout=self.request_timeout)
        # print(response)
        if response.status_code == 200:
            return response.text if to_text else response.content
        else:
            raise Exception(f'Failed with response code: {response.status_code}')

    def _create_out_dirs(self):
        os.makedirs(self.out_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _remove_out_dirs(self):
        shutil.rmtree(self.temp_dir)

    def _cleanup_out_dirs(self):
        if len(os.listdir(self.parent_temp_dir)) == 0: os.rmdir(self.parent_temp_dir)
        if len(os.listdir(self.out_dir)) == 0: os.rmdir(self.out_dir)

    def _exec_cmd(self, cmd):
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
        # print stdout to console
        msg = proc.communicate()[0].decode("utf-8")
        std_err = proc.communicate()[1].decode("utf-8")
        rc = proc.returncode
        if rc != 0:
            raise Exception(f"Error occured: {std_err}")
        return msg

    def _is_encrypted(self, m3u8_data):
        method = re.search('#EXT-X-KEY:METHOD=(.*),', m3u8_data)
        if method is None: return False
        if method.group(1) == "NONE": return False

        return True

    def _collect_uri_iv(self, m3u8_data):
        uri_iv = re.search('#EXT-X-KEY:METHOD=AES-128,URI="(.*)",IV=(.*)', m3u8_data)

        if uri_iv is None:
            uri_data = re.search('#EXT-X-KEY:METHOD=AES-128,URI="(.*)"', m3u8_data)
            return uri_data.group(1), None

        uri = uri_iv.group(1)
        iv = uri_iv.group(2)

        return uri, iv

    def _collect_ts_urls(self, m3u8_link, m3u8_data):
        urls = [url.group(0) for url in re.finditer("https://(.*)\.ts(.*)", m3u8_data)]
        if len(urls) == 0:
            # Relative paths
            base_url = '/'.join(m3u8_link.split('/')[:-1])
            urls = [base_url + "/" + url.group(0) for url in re.finditer("(.*)\.ts(.*)", m3u8_data)]
            if len(urls) == 0:
                # get all components not only .ts
                urls = [base_url + "/" + url.group(0) for url in re.finditer('ep\.(.*)', m3u8_data)]

        return urls

    @retry()
    def _download_segment(self, ts_url):
        try:
            segment_file_nm = ts_url.split('/')[-1]
            segment_file = os.path.join(f"{self.temp_dir}", f"{segment_file_nm}")

            if os.path.isfile(segment_file) and os.path.getsize(segment_file) > 0:
                return f'Segment file [{segment_file_nm}] already exists. Reusing.'

            with open(segment_file, "wb") as ts_file:
                ts_file.write(self._get_stream_data(ts_url))

            return f'Segment file [{segment_file_nm}] downloaded'

        except Exception as e:
            return f'\nERROR: Segment download failed [{segment_file_nm}] due to: {e}'

    def _download_segments(self, ts_urls):
        # print(f'[Epsiode-{ep_no}] Downloading {len(ts_urls)} segments using {self.concurrency} workers...')
        reused_segments = 0
        failed_segments = 0
        # shorten the name to show only ep number
        try:
            ep_no = self.out_file.split()[-3]
            try:
                ep_no = f'Epsiode-{int(ep_no):02d}'
            except ValueError as ve:
                ep_no = f'Movie' if ep_no.lower() == 'movie' else f'Epsiode-{ep_no}'
        except:
            ep_no = f'Movie'
        # show progress of download
        with tqdm(total=len(ts_urls), desc=f'Downloading {ep_no}', unit='seg', leave=True, file=sys.stdout, ascii='░▒█') as progress:
            # parallelize download of segments using a threadpool
            with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix='udb-m3u8-') as executor:
                results = [ executor.submit(self._download_segment, ts_url) for ts_url in ts_urls ]
                for result in as_completed(results):
                    status = result.result()
                    if 'ERROR' in status:
                        print(status)
                        failed_segments += 1
                    elif 'Reusing' in status:
                        reused_segments += 1
                        # update status only if segment is downloaded
                        progress.update()
                    else:
                        progress.update()
                    # add reused / failed segments status
                    seg_status = f'R/F: {reused_segments}/{failed_segments}'
                    progress.set_postfix_str(seg_status, refresh=True)

        if debug: print(f'[{ep_no}] Segments download status: Total: {len(ts_urls)} | Reused: {reused_segments} | Failed: {failed_segments}')
        if failed_segments > 0:
            raise Exception(f'Failed to download {failed_segments} / {len(ts_urls)} segments')

    def _rewrite_m3u8_file(self, m3u8_data):
        # regex safe temp dir path
        seg_temp_dir = self.temp_dir.replace('\\', '\\\\')
        # ffmpeg doesn't accept backward slash in key file irrespective of platform
        key_temp_dir = self.temp_dir.replace('\\', '/')
        with open(self.m3u8_file, "w") as m3u8_f:
            m3u8_content = re.sub('URI=(.*)/', f'URI="{key_temp_dir}/', m3u8_data, count=1)
            regex_safe = '\\\\' if os.sep == '\\' else '/'
            m3u8_content = re.sub(r'https://(.*)/', f'{seg_temp_dir}{regex_safe}', m3u8_content)
            m3u8_f.write(m3u8_content)

    def _convert_to_mp4(self):
        # print(f'Converting {self.out_file} to mp4')
        out_file = os.path.join(f'{self.out_dir}', f'{self.out_file}')
        cmd = f'ffmpeg -loglevel warning -allowed_extensions ALL -i "{self.m3u8_file}" -c copy -bsf:a aac_adtstoasc "{out_file}"'
        self._exec_cmd(cmd)

    def m3u8_downloader(self, m3u8_link):
        # create output directory
        self._create_out_dirs()

        iv = None
        m3u8_data = self._get_stream_data(m3u8_link, True)

        is_encrypted = self._is_encrypted(m3u8_data)
        if is_encrypted:
            key_uri, iv = self._collect_uri_iv(m3u8_data)
            self._download_segment(key_uri)

        # did not run into HLS with IV during development, so skipping it
        if iv:
            raise Exception("Current code cannot decode IV links")

        ts_urls = self._collect_ts_urls(m3u8_link, m3u8_data)
        self._download_segments(ts_urls)
        self._rewrite_m3u8_file(m3u8_data)
        self._convert_to_mp4()

        # remove temp dir once completed and dir is empty
        self._remove_out_dirs()

        return (0, None)


def downloader(ep_details, dl_config):
    '''
    download function where HLS Client initialization and download happens
    Accepts two dicts: download config, episode details
    Returns download status
    '''
    m3u8_url = ep_details['m3u8Link']
    referer = ep_details['refererLink']
    out_file = ep_details['episodeName']
    out_dir = dl_config['download_dir']
    # create download client for the episode
    dlClient = HLSDownloader(dl_config, referer, out_file)

    get_current_time = lambda fmt='%F %T': datetime.now().strftime(fmt)
    start = get_current_time()
    start_epoch = int(time())
    if debug: print(f'[{start}] Download started for {out_file}...')

    if os.path.isfile(os.path.join(f'{out_dir}', f'{out_file}')):
        # skip file if already exists
        return f'[{start}] Download skipped for {out_file}. File already exists!'
    else:
        try:
            # main function where HLS download happens
            status, msg = dlClient.m3u8_downloader(m3u8_url)
        except Exception as e:
            status, msg = 1, str(e)

        # remove target dirs if no files are downloaded
        dlClient._cleanup_out_dirs()

        end = get_current_time()
        if status != 0:
            return f'[{end}] Download failed for {out_file}. {msg}'

        def pretty_time(sec):
            h, m, s = sec // 3600, sec % 3600 // 60, sec % 3600 % 60
            return '{:02d}h {:02d}m {:02d}s'.format(h,m,s) if h > 0 else '{:02d}m {:02d}s'.format(m,s)
        end_epoch = int(time())
        download_time = pretty_time(end_epoch-start_epoch)
        return f'[{end}] Download completed for {out_file} in {download_time}!'

# if __name__ == '__main__':
#     config = {'download_dir': r'C:\Users\HP\Downloads\Video\Eulachacha Waikiki 2 (2019) temp',
#               'temp_download_dir': r'C:\Users\HP\Downloads\Video\Eulachacha Waikiki 2 (2019)\temp_dir',
#               'concurrency_per_file': 4,
#               'request_timeout': 30
#     }
#     dict = {'episodeId': 'bd89c830c98859006cdce06eb5ba92a885fe9278f98734434dc84b98b0006e5b', 'episodeLink': 'https://animepahe.com/play/1f4869d2-0cfb-4680-59c9-7ff936726d30/bd89c830c98859006cdce06eb5ba92a885fe9278f98734434dc84b98b0006e5b', 'episodeName': 'Gokushufudou Season 2 episode 4 - 360P.mp4', 'refererLink': 'https://kwik.cx/e/sdl9rsfFlVts', 'm3u8Link': 'https://eu-111.cache.nextcdn.org/stream/11/03/1ad144913c0b8b1e4f9c22a041627ddaff21fffc0b23aa5afee00fc3663410e1/uwu.m3u8'}
#     print(downloader(dict, config))