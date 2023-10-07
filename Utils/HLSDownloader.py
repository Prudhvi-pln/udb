__author__ = 'Prudhvi PLN'

import os
import re

from Utils.commons import retry
from Utils.BaseDownloader import BaseDownloader


class HLSDownloader(BaseDownloader):
    '''Download Client for HLS files'''
    # References: https://github.com/Oshan96/monkey-dl/blob/master/anime_downloader/util/hls_downloader.py
    # https://github.com/josephcappadona/m3u8downloader/blob/master/m3u8downloader/m3u8.py

    def __init__(self, dl_config, referer_link, out_file, session=None):
        # initialize base downloader
        super().__init__(dl_config, referer_link, out_file, session)
        # initialize HLS specific configuration
        self.m3u8_file = os.path.join(f'{self.temp_dir}', 'uwu.m3u8')
        self.thread_name_prefix = 'udb-m3u8-'

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
        # Case-1: typical HLS with AES-128
        urls = [url.group(0) for url in re.finditer("https://(.*)\.ts(.*)", m3u8_data)]
        if len(urls) == 0:
            # Case-2: case-1 with relative paths
            base_url = '/'.join(m3u8_link.split('/')[:-1])
            urls = [base_url + "/" + url.group(0) for url in re.finditer("(.*)\.ts(.*)", m3u8_data)]
            if len(urls) == 0:
                # Case-3: sometimes HLS contain .css, .jpg and others. So, get all components not only .ts
                urls = [base_url + "/" + url.group(0) for url in re.finditer('ep\.(.*)', m3u8_data)]

        if len(urls) == 0:
            # Case-4: HLS for AV1 codec
            urls = [ url.group(0).replace('"', '') for url in re.finditer("https://(.*)", m3u8_data) ]

        return urls

    @retry()
    def _download_segment(self, ts_url):
        '''
        download segment file from url. Reuse if already downloaded.

        Returns: (download_status, progress_bar_increment)
        '''
        try:
            segment_file_nm = ts_url.split('/')[-1]
            segment_file = os.path.join(f"{self.temp_dir}", f"{segment_file_nm}")

            # check if the segment is already downloaded
            if os.path.isfile(segment_file) and os.path.getsize(segment_file) > 0:
                return (f'Segment file [{segment_file_nm}] already exists. Reusing.', 1)

            with open(segment_file, "wb") as ts_file:
                ts_file.write(self._get_stream_data(ts_url))

            return (f'Segment file [{segment_file_nm}] downloaded', 1)

        except Exception as e:
            return (f'\nERROR: Segment download failed [{segment_file_nm}] due to: {e}', 0)

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

    def start_download(self, m3u8_link):
        # create output directory
        self.logger.debug('Creating output directories')
        self._create_out_dirs()

        iv = None
        self.logger.debug('Fetching stream data')
        m3u8_data = self._get_stream_data(m3u8_link, True)

        self.logger.debug('Check if stream is encrypted')
        is_encrypted = self._is_encrypted(m3u8_data)
        if is_encrypted:
            self.logger.debug('Stream is encrypted. Collect iv data and download key')
            key_uri, iv = self._collect_uri_iv(m3u8_data)
            self._download_segment(key_uri)

        # did not run into HLS with IV during development, so skipping it
        if iv:
            raise Exception("Current code cannot decode IV links")

        self.logger.debug('Collect .ts segment urls')
        ts_urls = self._collect_ts_urls(m3u8_link, m3u8_data)

        self.logger.debug('Downloading collected .ts segments')
        metadata = {
            'type': 'segments',
            'total': len(ts_urls),
            'unit': 'seg'
        }
        self._multi_threaded_download(self._download_segment, ts_urls, **metadata)

        self.logger.debug('Rewrite m3u8 file with downloaded .ts segments paths')
        self._rewrite_m3u8_file(m3u8_data)

        self.logger.debug('Converting .ts files to .mp4')
        self._convert_to_mp4()

        # remove temp dir once completed and dir is empty
        self.logger.debug('Removing temporary directories')
        self._remove_out_dirs()

        return (0, None)


# if __name__ == '__main__':
#     config = {'download_dir': r'C:\Users\HP\Downloads\Video\Eulachacha Waikiki 2 (2019) temp',
#               'temp_download_dir': r'C:\Users\HP\Downloads\Video\Eulachacha Waikiki 2 (2019)\temp_dir',
#               'concurrency_per_file': 4,
#               'request_timeout': 30
#     }
#     dict = {'episodeId': 'bd89c830c98859006cdce06eb5ba92a885fe9278f98734434dc84b98b0006e5b', 'episodeLink': 'https://animepahe.com/play/1f4869d2-0cfb-4680-59c9-7ff936726d30/bd89c830c98859006cdce06eb5ba92a885fe9278f98734434dc84b98b0006e5b', 'episodeName': 'Gokushufudou Season 2 episode 4 - 360P.mp4', 'refererLink': 'https://kwik.cx/e/sdl9rsfFlVts', 'downloadLink': 'https://eu-111.cache.nextcdn.org/stream/11/03/1ad144913c0b8b1e4f9c22a041627ddaff21fffc0b23aa5afee00fc3663410e1/uwu.m3u8'}
#     print(downloader(dict, config))
