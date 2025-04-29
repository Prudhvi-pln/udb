__author__ = 'Prudhvi PLN'

import json
import logging
import re
import requests
import os
from bs4 import BeautifulSoup as BS
from copy import deepcopy
from urllib.parse import parse_qs, urlparse

# modules for encryption
import base64
from Cryptodome.Cipher import AES

# modules to bypass DDoS protection & Complex Javascript execution
import undetected_chromedriver as uc

from Utils.commons import colprint, exec_os_cmd, pretty_time, retry, threaded, ExitException


class BaseClient():
    '''
    Base Client Implementation for Site-specific clients
    '''
    def __init__(self, request_timeout=30, session=None):
        # create a requests session and use across to re-use cookies
        self.req_session = session if session else requests.Session()
        self.request_timeout = request_timeout
        try:
            self.hls_size_accuracy
        except AttributeError:
            self.hls_size_accuracy = 0      # set default value if not set

        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept-Encoding": "*",
            "Connection": "keep-alive"
        }
        self.udb_episode_dict = {}   # dict containing all details of epsiodes
        self.cookies_file = os.path.join(os.path.dirname(__file__), '.udb_client_cookies.json')      # file containing re-usable cookies
        # list of invalid characters not allowed in windows file system
        self.invalid_chars = ['/', '\\', '"', ':', '?', '|', '<', '>', '*']
        self.bs = AES.block_size
        # get the root logger
        self.logger = logging.getLogger()
        # re-usable lambda functions
        self._regex_extract = lambda rgx, txt, grp: re.search(rgx, txt).group(grp) if re.search(rgx, txt) else False

    def _update_udb_dict(self, parent_key, child_dict):
        if parent_key in self.udb_episode_dict:
            self.udb_episode_dict[parent_key].update(child_dict)
        else:
            self.udb_episode_dict[parent_key] = child_dict
        self.logger.debug(f'Updated udb dict: {self.udb_episode_dict}')

    def _get_udb_dict(self):
        return self.udb_episode_dict

    def _colprint(self, theme, text, **kwargs):
        '''
        Wrapper for color printer function
        '''
        if 'input' in theme:
            return colprint(theme, text, **kwargs)
        else:
            colprint(theme, text, **kwargs)

    def _exit(self, code):
        '''
        Wrapper to raise ExitException
        '''
        raise ExitException(code)

    @retry()
    def _send_request(self, url, referer=None, request_type='get', extra_headers=None, cookies={}, return_type='text', post_data=None, upload_data=None, silent=False):
        '''
        call response session and return response

        Argument:
        - return_type - valid options are text/json/bytes/raw
        - silent: boolean - suppress logging errors
        '''
        def _conditional_logger(silent, message):
            if silent:
                self.logger.warning(f'[Suppressed error] {message}')
            else:       # display error message onto console and log
                self.logger.error(message)

        # print(f'{self.req_session}: {url}')
        header = deepcopy(self.header)
        if referer: header.update({'referer': referer})
        if return_type.lower() == 'json': header.update({'Accept': 'application/json'})
        if extra_headers: header.update(extra_headers)
        # self.logger.debug(f'Cookies before request: {self.req_session.cookies.get_dict()}')
        if request_type == 'get':
            response = self.req_session.get(url, timeout=self.request_timeout, headers=header, cookies=cookies)
        elif request_type == 'post':
            response = self.req_session.post(url, timeout=self.request_timeout, headers=header, cookies=cookies, data=post_data, files=upload_data)
        # self.logger.debug(f'Cookies after request: {self.req_session.cookies.get_dict()}')
        # print(response)

        if response.status_code == 200:
            if return_type.lower() == 'text':
                return response.text
            elif return_type.lower() == 'bytes':
                return response.content
            elif return_type.lower() == 'json':
                try:
                    return response.json()
                except json.JSONDecodeError as jde:
                    _conditional_logger(silent, f'Invalid JSON response received')
            elif return_type.lower() == 'raw':
                return response

        elif str(response.status_code).startswith('5'):     # retry if status code is 5xx
            msg = f'Failed with code: {response.status_code}'
            self.logger.warning(msg)
            raise Exception(msg)

        elif response.status_code == 404:                   # raise exception if status code is 4xx
            msg = f'Failed with code: {response.status_code}. Page not found for {url}'
            self.logger.error(msg)
            # raise Exception(msg)

        else:
            _conditional_logger(silent, f'Failed with code: {response.status_code}')

    def _get_bsoup(self, search_url, referer=None, request_type='get', extra_headers=None, cookies={}, post_data=None, upload_data=None, silent=False):
        '''
        return html parsed soup
        '''
        html_content = self._send_request(search_url, referer=referer, request_type=request_type, extra_headers=extra_headers, cookies=cookies, return_type='text', post_data=post_data, upload_data=upload_data, silent=silent)
        if html_content is not None:
            return BS(html_content, 'html.parser')

    def _exec_cmd(self, cmd):
        return exec_os_cmd(cmd)

    def _windows_safe_string(self, word):
        for i in self.invalid_chars:
            word = word.replace(i, '')

        return word

    def _safe_type_cast(self, val):
        try:
            value = f'{val:02d}'
        except ValueError as ve:
            value = f'{val}'

        return value

    def _load_udb_cookies(self, client):
        self.logger.debug('Reloading saved cookies...')

        if os.path.isfile(self.cookies_file):
            self.logger.debug(f'Last loaded cookies file found [{self.cookies_file}]. Reloading cookies...')
            # Reload last saved cookies
            with open(self.cookies_file) as f:
                cookies = json.loads(f.read())

            if client in cookies:
                self.logger.debug(f'Cookies loaded from file: {cookies[client]}')
                return cookies[client]
            else:
                self.logger.debug(f'No Cookies found for {client}! Loading new cookies...')

        else:
            self.logger.debug(f'Last loaded cookies file not found [{self.cookies_file}]. Loading new cookies...')

        return {}

    def _save_udb_cookies(self, client, data):
        self.logger.debug(f'Saving extracted new cookies to file: {data}')
        # Save the new cookies to file
        if os.path.isfile(self.cookies_file):
            with open(self.cookies_file) as f:
                cookies = json.loads(f.read())
        else:
            cookies = {}
        cookies[client] = data
        with open(self.cookies_file, 'w') as f:
            json.dump(cookies, f)

    # step-4.1 -- used in GogoAnime, MyAsianTV
    def _get_stream_link(self, link, stream_links_element):
        '''
        return stream link for extracting download links
        '''
        pad_https = lambda x: 'https:' + x if x.startswith('/') else x
        self.logger.debug(f'Extract stream link from soup for {link = }')
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        for stream in soup.select(stream_links_element):
            if 'iframe' in stream_links_element:
                stream_link = stream['src']
                return pad_https(stream_link)
            elif 'active' in stream.get('class'):
                stream_link = stream['data-video']
                return pad_https(stream_link)

    # step-4.2.2.1 -- used in GogoAnime, MyAsianTV
    def _parse_m3u8_links(self, master_m3u8_link, referer):
        '''
        parse master m3u8 data and return dict of resolutions and m3u8 links
        '''
        m3u8_links = {}
        base_url = '/'.join(master_m3u8_link.split('/')[:-1])
        self.logger.debug(f'Extracting m3u8 data from master link: {master_m3u8_link}')
        master_m3u8_data = self._send_request(master_m3u8_link, referer=referer)
        # self.logger.debug(f'{master_m3u8_data = }')

        _regex_list = lambda data, rgx, grp: [ url.group(grp) for url in re.finditer(rgx, data) ]
        _full_link = lambda link: link if link.startswith('http') else base_url + '/' + link
        resolutions = _regex_list(master_m3u8_data, r'RESOLUTION=(\d+x\d+)', 1)
        resolution_names = _regex_list(master_m3u8_data, 'NAME="(.*)"', 1)
        if len(resolution_names) == 0:
            resolution_names = [ res.lower().split('x')[-1] for res in resolutions ]
        resolution_links = _regex_list(master_m3u8_data, '(.*)m3u8', 0)
        self.logger.debug(f'Resolutions data: {resolutions = }, {resolution_names = }, {resolution_links = }')

        if len(resolution_links) == 0:
            # check for original keyword in the link, or if '#EXT-X-ENDLIST' in m3u8 data
            self.logger.debug('Child resolutions not found. Checking if master link is original link')
            master_is_child = re.search('#EXT-X-ENDLIST', master_m3u8_data)
            if 'original' in master_m3u8_link or master_is_child:
                self.logger.debug('master m3u8 link itself is the download link')
                # treat is as mp4 to fetch metadata using ffprobe
                duration, size, resolution = self._get_video_metadata(master_m3u8_link, 'mp4', referer)
                _res_key = resolution.split('x')[-1] if resolution else '1080'
                m3u8_links[_res_key] = {
                    'resolution_size': resolution,
                    'downloadLink': master_m3u8_link,
                    'downloadType': 'hls',
                    'duration': pretty_time(duration)
                }
                # get approx download size and add file size if available
                file_size = self._get_download_size(master_m3u8_link, referer)
                if file_size: m3u8_links['1080'].update({'filesize_mb': file_size})

            return m3u8_links

        # calculate duration from any resolution, as it is same for all resolutions
        temp_link = _full_link(resolution_links[0]) if resolution_links else master_m3u8_link
        duration = pretty_time(self._get_video_metadata(temp_link, 'hls', referer)[0])

        for _res, _pixels, _link in zip(resolution_names, resolutions, resolution_links):
            # prepend base url if it is relative url
            m3u8_link = _full_link(_link)
            m3u8_links[_res.replace('p','')] = {
                'resolution_size': _pixels,
                'downloadLink': m3u8_link,
                'downloadType': 'hls',
                'duration': duration
            }
            # get approx download size and add file size if available
            file_size = self._get_download_size(m3u8_link, referer)
            if file_size: m3u8_links[_res.replace('p','')].update({'filesize_mb': file_size})

        return m3u8_links

    # step-4.2.2.2 -- used in GogoAnime, MyAsianTV
    def _get_video_metadata(self, link, link_type='mp4', referer=None):
        '''
        return duration & size of the video using ffprobe command
        Note: size is available only for mp4 links
        '''
        duration, size, resolution = 0, None, None
        try:
            # Note: ffprobe is taking 3-10s, so try to avoid as much as possible
            if link_type == 'hls':
                self.logger.debug('Fetching video duration by parsing video link')
                data = self._send_request(link)
                duration = sum([ float(match.group(1)) for match in re.finditer('#EXTINF:(.*),', data) ])
            else:
                # add -show_streams in ffprobe to get more information
                ffprobe_cmd = f'ffprobe -extension_picky 0 -allowed_extensions ALL -loglevel quiet -print_format json -show_format -select_streams v:0 -show_entries stream=width,height'
                if referer:
                    ffprobe_cmd += f' -referer "{referer}"'
                self.logger.debug(f'Fetching video duration using ffprobe command: {ffprobe_cmd} "{link}"')
                video_metadata = json.loads(self._exec_cmd(f'{ffprobe_cmd} "{link}"'))
                duration = float(video_metadata.get('format', {}).get('duration', 0))
                size = float(video_metadata.get('format', {}).get('size', 0))
                resolution = f"{video_metadata.get('streams', [{}])[0].get('width')}x{video_metadata.get('streams', [{}])[0].get('height')}"
                self.logger.debug(f'Size fetched is {size} bytes, Resoltion: {resolution}')

            self.logger.debug(f'Duration fetched is {duration} seconds')

        except Exception as e:
            self.logger.warning(f'Failed to fetch video duration. Error: {e}')

        return round(duration), size, resolution

    @threaded()
    def _fetch_content_length(self, url):
        try:
            content_len = float(requests.get(url).headers.get('content-length', 0))
        except Exception as e:
            self.logger.warning(f'Failed to fetch video content length for {url = }. Error: {e}')
            content_len = 0

        return content_len

    # step-4.2.2.1.1
    def _get_download_size(self, m3u8_link, referer=None):
        '''
        return the download file size (in MB) of a HLS stream based on estimation quality.
        '''
        try:
            if self.hls_size_accuracy == 0:     # this parameter should be defined in respective client initialization
                return None                     # do nothing if disabled
            self.logger.debug(f'Calculating download size for {m3u8_link = }')
            m3u8_data = self._send_request(m3u8_link, referer=referer)
            # extract ts segment urls. same as in HLS downloader
            base_url = '/'.join(m3u8_link.split('/')[:-1])
            normalize_url = lambda url, base_url: (url if url.startswith('http') else f'{base_url}/{url}')
            urls = [ normalize_url(url.group(0), base_url) for url in re.finditer("^(?!#).+$", m3u8_data, re.MULTILINE) ]

            # Logic for 'approx' quality: find content size of a few segments and multiply the average with number of segments
            tgt_len = len(urls) * self.hls_size_accuracy // 100
            url_set = urls[:tgt_len]
            # define correction factor to adjust the estimated size
            cf = 0.85 if self.hls_size_accuracy < 95 else 0.9
            self.logger.debug(f'Segments considered based on accuracy of {self.hls_size_accuracy}% is {tgt_len}/{len(urls)}. Correction factor: {cf}')
            content_lens = self._fetch_content_length(url_set)

            # calculate total file size in bytes
            if self.hls_size_accuracy == 100:
                dl_size = sum(content_lens) * cf   # cf is required as video compresses after converting to mp4
            else:
                avg_content_len = sum(content_lens) / len(content_lens)
                dl_size = avg_content_len * len(urls) * cf

            dl_size = round(dl_size / (1024**2))         # bytes to MB
            self.logger.debug(f'Download size is {dl_size} MB')

        except Exception as e:
            self.logger.warning(f'Failed to fetch download size for {m3u8_link = }. Error: {e}')
            dl_size = None

        return dl_size

    # step-4.2.1 -- used in GogoAnime, MyAsianTV
    def _get_download_sources(self, **gdl_config):
        '''
        extract download link sources
        '''
        self.logger.debug(f'Received get download links config: {gdl_config = }')

        # unpack configuration dictionary
        link = gdl_config['link']
        encrypted_url_args_regex = gdl_config['encrypted_url_args_regex']
        download_fetch_link = gdl_config['download_fetch_link']

        # extract encryption, decryption keys and iv
        stream_page_content = self._send_request(link, return_type='bytes')

        # get encryption, decryption keys and iv
        if 'crypt_keys_regex' in gdl_config:
            crypt_keys_regex = gdl_config['crypt_keys_regex']
            try:
                encryption_key, iv, decryption_key = (
                    _.group(1) for _ in crypt_keys_regex.finditer(stream_page_content)
                )
                self.logger.debug(f'Extracted {encryption_key = }, {decryption_key = }, {iv = }')

            except Exception as e:
                return {'error': f'Failed to extract encryption keys. Error: {e}'}

        else:
            encryption_key = gdl_config['encryption_key']
            decryption_key = gdl_config['decryption_key']
            iv = gdl_config['iv']

        # get encrypted url arguments and decrypt
        try:
            encrypted_args = encrypted_url_args_regex.search(stream_page_content).group(1)
            self.logger.debug(f'Extracted {encrypted_args = }')
            if encrypted_args is None or encrypted_args == '':
                raise Exception('Encrypted url arguments not found in stream link')

            self.logger.debug('Decrypting extracted url arguments')
            decrypted_args = self._aes_decrypt(encrypted_args, encryption_key, iv)
            self.logger.debug(f'{decrypted_args = }')
            if decrypted_args is None or decrypted_args == '':
                raise Exception('Failed to decrypt extracted url arguments')

        except Exception as e:
            return {'error': f'Failed to fetch download url arguments. Error: {e}'}

        # extract url params & get id value
        try:
            uid = parse_qs(urlparse(link).query).get('id')[0]
            self.logger.debug(f'Extracted {uid = }')
            if uid is None or uid == '':
                raise Exception('ID not found in stream link')
        except Exception as e:
            return {'error': f'Failed to fetch Stream ID with error: {e}'}

        # encrypt the uid and construct download link with required parameters
        self.logger.debug(f'Creating encrypted link')
        encrypted_uid = self._aes_encrypt(uid, encryption_key, iv)
        self.logger.debug(f'{encrypted_uid = }')
        stream_base_url = '/'.join(link.split('/')[:3])
        dl_sources_link = f'{stream_base_url}/{download_fetch_link}?id={encrypted_uid}&alias={decrypted_args}'
        self.logger.debug(f'{dl_sources_link = }')

        try:
            # get encrpyted response with download links
            self.logger.debug(f'Fetch download links from encrypted url')
            encrypted_response = self._send_request(dl_sources_link, referer=link, extra_headers={'x-requested-with': 'XMLHttpRequest'}, return_type='json')['data']
            self.logger.debug(f'{encrypted_response = }')

            # decode the response
            self.logger.debug(f'Decoding the response')
            decoded_response = self._aes_decrypt(encrypted_response, decryption_key, iv)
            self.logger.debug(f'{decoded_response = }')
            decoded_response = json.loads(decoded_response)

        except Exception as e:
            return {'error': f'Invalid response received. Error: {e}'}

        # extract & flatten all download links (including source & backup) from decoded response
        download_links = []
        for key in ['source', 'source_bk']:
            if decoded_response.get(key, '') != '':
                download_links.extend(decoded_response.get(key))

        self.logger.debug(f'Extracted links: {download_links = }')
        if len(download_links) == 0:
            return {'error': 'No download links found'}

        return download_links

    # step-4.2.2 -- used in GogoAnime, MyAsianTV, VidSrc
    def _get_download_links(self, download_links, *config_data):
        '''
        retrieve download links from stream link and return available resolution links
        - Sort the resolutions in ascending order
        '''
        link, preferred_urls, blacklist_urls = config_data
        pad_https = lambda x: 'https:' + x if x.startswith('//') else x
        # re-order urls based on user preference
        ordered_download_links = [ j for i in preferred_urls for j in download_links if i in j.get('file') ]
        # append remaining urls
        ordered_download_links.extend([ j for j in download_links if j not in ordered_download_links ])
        # remove blacklisted urls
        ordered_download_links = [ j for j in ordered_download_links if not any(i in j.get('file') for i in blacklist_urls) ]

        self.logger.debug(f'{ordered_download_links = }')
        if len(ordered_download_links) == 0:
            return {'error': 'No download links found after filtering'}

        # extract resolution links from source links
        self.logger.debug('Extracting resolution download links...')
        counter = 0
        resolution_links = {}

        for download_link in ordered_download_links:
            counter += 1
            dlink = pad_https(download_link.get('file'))
            dtype = download_link.get('type', '').strip().lower()
            # set default download type as HLS if link name ends with m3u8
            if dtype == '' and dlink.split('?')[0].endswith('.m3u8'):
                dtype = 'hls'

            if dtype == 'hls':
                try:
                    # extract inner m3u8 resolution links from master m3u8 link
                    self.logger.debug(f'Found m3u8 link. Getting m3u8 links from master m3u8 link [{dlink}]')
                    m3u8_links = self._parse_m3u8_links(dlink, link)
                    self.logger.debug(f'Returned {m3u8_links = }')

                    if len(m3u8_links) > 0:
                        self.logger.debug('m3u8 links obtained. No need to try with alternative. Breaking loop')
                        resolution_links.update(m3u8_links)
                        break

                except Exception as e:
                    # try with alternative master m3u8 link
                    self.logger.warning(f'Failed to fetch m3u8 links from {dlink = } with error: {e}. Trying with alternative...')
                    if counter >= len(ordered_download_links):
                        self.logger.warning('No other alternatives found')

            elif dtype == 'mp4':
                # if link is mp4, it is a direct download link
                self.logger.debug(f'Found mp4 link. Adding the direct download link [{dlink}]')
                duration, file_size, resolution = self._get_video_metadata(dlink, link_type='mp4', referer=link)
                duration = pretty_time(duration)
                resltn = resolution.split('x')[-1]
                resolution_links[resltn] = {
                    'resolution_size': resolution,
                    'downloadLink': dlink,
                    'downloadType': 'mp4',
                    'duration': duration
                }
                # get actual download size and add file size if available
                if file_size:
                    file_size = round(file_size / (1024**2))    # Bytes to MB
                    resolution_links[resltn].update({'filesize_mb': file_size})

            else:
                # unknown download type
                self.logger.warning(f'Unknown download type [{dtype}] for link [{dlink}]')

        if resolution_links:      # sort the resolutions in ascending order
            resolution_links = dict(sorted(resolution_links.items(), key=lambda x: int(x[0])))

        self.logger.debug(f'Sorted resolution links: {resolution_links = }')

        return resolution_links

    # step-4.3
    def _show_episode_links(self, key, details, display_prefix='Episode'):
        '''
        pretty print episode links from fetch_episode_links. (this is a default method. override if required)
        '''
        info = f"{display_prefix}: {self._safe_type_cast(key)}"
        if 'error' in details:
            info += f' | {details["error"]}'
            self.logger.error(info)
            return

        try:
            duration = next(iter(details.values())).get("duration", "NA")
        except:
            duration = 'NA'
        info += f' (duration: {duration})'    # get duration from any resolution dict

        for _res, _vals in details.items():
            info += f' | {_res}P ({_vals["resolution_size"]})' #| URL: {_vals["downloadLink"]}
            if 'filesize_mb' in _vals: info += f' [~{_vals["filesize_mb"]} MB]'

        self._colprint('results', info)

    # step-6
    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution. (this is a default method. override if required)
        '''
        _get_ep_name = lambda resltn: f"{self.udb_episode_dict.get(ep).get('episodeName')} - {resltn}P.mp4"

        display_prefix = 'Episode'
        series_flag = True if str(next(iter(target_links.keys()))).startswith('s') else False
        if series_flag: prev_season = None

        for ep, link in target_links.items():
            error = None

            if series_flag:
                cur_season = int(ep.split('e')[0].replace('s', ''))
                ep_no = int(ep.split('e')[-1])
                if prev_season != cur_season:
                    self._colprint('results', f"-------------- Season: {cur_season:} --------------")
                    prev_season = cur_season
            elif type(ep) == str and ep.startswith('m'):
                display_prefix = 'Movie'
                ep_no = int(ep.replace('m', ''))
            elif self.udb_episode_dict.get(ep).get('episodeName').endswith('Movie'):
                display_prefix = 'Movie'
                ep_no = ep
            else:
                ep_no = ep

            self.logger.debug(f'{display_prefix}: {ep}, Link: {link}')
            info = f'{display_prefix}: {self._safe_type_cast(ep_no)} |'

            # select the resolution based on the selection strategy
            selected_resolution = self._resolution_selector(link.keys(), resolution, self.selector_strategy)
            res_dict = link.get(selected_resolution)
            self.logger.debug(f'{selected_resolution = } based on {self.selector_strategy = }, Data: {res_dict = }')

            if 'error' in link:
                error = link.get('error')

            elif res_dict is None or len(res_dict) == 0:
                error = f'Resolution [{resolution}] not found'

            else:
                info = f'{info} {selected_resolution}P |'
                try:
                    ep_name = _get_ep_name(selected_resolution)
                    ep_link = res_dict['downloadLink']
                    link_type = res_dict['downloadType']

                    # add download link and it's type against episode
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'downloadLink': ep_link, 'downloadType': link_type})
                    self.logger.debug(f'{info} Link found [{ep_link}]')
                    self._colprint('results', f'{info} Link found [{ep_link}]')

                except Exception as e:
                    error = f'Failed to fetch link with error [{e}]'

            if error:
                # add error message and log it
                ep_name = _get_ep_name(resolution)
                self._update_udb_dict(ep, {'episodeName': ep_name, 'error': error})
                self.logger.error(f'{info} {error}')

        final_dict = { k:v for k,v in self._get_udb_dict().items() }

        return final_dict

    def _pad(self, s):
        return s + (self.bs - len(s) % self.bs) * chr(self.bs - len(s) % self.bs)

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def _aes_encrypt(self, word: str, key: bytes, iv: bytes):
        # [deprecated] using openssl
        # cmd = f'echo {word} | "{openssl_executable}" enc -aes256 -K {key} -iv {iv} -a -e'
        # Encrypt the message and add PKCS#7 padding
        padded_message = self._pad(word)
        # set up the AES cipher in CBC mode
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted_message = cipher.encrypt(padded_message.encode('utf-8'))
        # Base64-encode the encrypted message
        base64_encrypted_message = base64.b64encode(encrypted_message).decode('utf-8')

        return base64_encrypted_message

    def _aes_decrypt(self, word: str, key: bytes, iv: bytes):
        # [deprecated] using openssl
        # Decode the base64-encoded message
        # cmd = f'echo {word} | python -m base64 -d | "{openssl_executable}" enc -aes256 -K {key} -iv {iv} -d'
        encrypted_msg = base64.b64decode(word)
        # set up the AES cipher in CBC mode
        cipher = AES.new(key, AES.MODE_CBC, iv)
        # Decrypt the message and remove the PKCS#7 padding
        decrypted_msg = self._unpad(cipher.decrypt(encrypted_msg))
        # get the decrypted message using UTF-8 encoding
        decrypted_msg = decrypted_msg.decode('utf-8').strip()

        return decrypted_msg

    def _get_episode_range_to_show(self, start, end, predefined_range=None, threshold=24, type='episodes'):
        '''
        Get the range of episodes from user and return the range to display
        '''
        if end - start <= threshold:        # if episode range is within threshold, display all
            return start, end

        default_range = f'{start}-{end}'
        if predefined_range:
            # display only required episodes if specified from cli
            show_range = predefined_range
        else:
            show_range = self._colprint('user_input', f'Enter {type} range to display (ex: 1-16) [default={default_range}]: ', input_type='recurring', input_dtype='range') or 'all'
            if show_range.lower() == 'all':
                show_range = default_range

        # fill the range if it is a relative range
        if show_range.startswith('-'):
            show_range = f'{start}{show_range}'
        elif show_range.endswith('-'):
            show_range = f'{show_range}{end}'
        # flatten the episode ranges into a sorted list and pick the first and last
        ep_selected_for_display = sorted([ float(i) for i in show_range.replace('-', ',').split(',') ])
        start, end = int(ep_selected_for_display[0]), int(ep_selected_for_display[-1])

        if show_range == default_range:
            self._colprint('header', 'Showing all episodes:')
        elif type != 'episodes':
            self._colprint('header', f'Showing episodes for {type} [{start} - {end}]:')
        else:
            self._colprint('header', f'Showing episodes from {start} to {end}:')

        return start, end

    def _resolution_selector(self, available_resolutions, target_resolution, selector_strategy='lowest'):
        '''
        Select a resolution based on selection strategy
        '''
        if 'error' in available_resolutions or len(available_resolutions) == 0:
            return

        if target_resolution in available_resolutions:
            return target_resolution

        # return if there is only one resolution available. Also helpful if resolution = original
        if len(available_resolutions) == 1:
            return next(iter(available_resolutions))

        sorted_resolutions = sorted(available_resolutions, key=lambda x: int(x))

        if selector_strategy == 'highest':
            # if selector_strategy is higher, select the next highest resolution
            for resolution in sorted_resolutions:
                if int(resolution) > int(target_resolution):
                    return resolution
            else:
                return resolution      # return highest resolution if reached end of loop

        elif selector_strategy == 'lowest':
            # if selector_strategy is lower, select the next lowest resolution
            for resolution in sorted_resolutions[::-1]:
                if int(resolution) < int(target_resolution):
                    return resolution
            else:
                return resolution      # return lowest resolution if reached start of loop

        else:
            return None

    def _get_undetected_chrome_driver(self, client):
        '''
        Get the undetected chrome driver based on installed Chrome broswer available.
        Args: client - name of the client (used for logging only)
        '''
        def __suppress_exception_in_del(uc):
            '''
            Suppress the exception saying "OSError: [WinError 6] The handle is invalid"
            '''
            old_del = uc.Chrome.__del__

            def new_del(self) -> None:
                try:
                    old_del(self)
                except:
                    pass
            
            setattr(uc.Chrome, '__del__', new_del)

        def __get_chrome_version(chrome_path):
            '''
            Get the Chrome version dynamically
            '''
            if '\\' in chrome_path:     # = Windows OS
                is_match = lambda word: re.search(r'\d+\.\d+\.\d+\.\d+', word)
                get_version = lambda path: [ is_match(d).group(0) for d in os.listdir(os.path.dirname(path)) if is_match(d) ][0]
                version = get_version(chrome_path)
            else:                       # = Linux OS
                version = self._exec_cmd(f"'{chrome_path}' --version").strip('Google Chrome ').strip()

            return int(version.split('.')[0])

        self.logger.debug('Suppressing exit exception in Chrome driver')
        __suppress_exception_in_del(uc)

        # check if chrome is installed
        self.logger.debug('Checking if Chrome is installed')
        chrome_path = uc.find_chrome_executable()
        if chrome_path is None or chrome_path == '':
            self.logger.error(f'{client} requires a chrome browser to be installed. Unable to proceed further!')
            self._exit(0)

        # dynamically fetch the chrome version
        self.logger.debug('Dynamically fetching the installed Chrome version')
        try:
            main_version = __get_chrome_version(chrome_path)
            self.logger.debug(f'Current chrome version: {main_version}')
        except Exception as e:
            self.logger.error(f'Failed to fetch Chrome version. Error: {e}')
            self._exit(0)

        return uc.Chrome(headless=True, version_main=main_version)

    # step-7
    def cleanup(self):
        '''
        Perform any clean-up activities as required.
        '''
        # Override this method with custom implementation in respective client
        pass
