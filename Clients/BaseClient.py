__author__ = 'Prudhvi PLN'

import json
import logging
import re
import requests
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter
from subprocess import Popen, PIPE
from urllib.parse import parse_qs, urlparse
from urllib3.util.retry import Retry

# modules for encryption used in Drama
import base64
from Cryptodome.Cipher import AES

from Utils.commons import retry


class BaseClient():
    def __init__(self, request_timeout=30, session=None):
        # create a requests session and use across to re-use cookies
        self.req_session = session if session else requests.Session()
        # self.req_session = session if session else cs.create_scraper()
        self.request_timeout = request_timeout
        # add retries with backoff
        retry = Retry(total=3, backoff_factor=0.1)
        adapter = HTTPAdapter(max_retries=retry)
        self.req_session.mount('http://', adapter)
        self.req_session.mount('https://', adapter)
        # disable insecure warnings
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Accept-Encoding": "*",
            "Connection": "keep-alive"
        }
        self.udb_episode_dict = {}   # dict containing all details of epsiodes
        # list of invalid characters not allowed in windows file system
        self.invalid_chars = ['/', '\\', '"', ':', '?', '|', '<', '>', '*']
        self.bs = AES.block_size
        # get the root logger
        self.logger = logging.getLogger()

    def _update_udb_dict(self, parent_key, child_dict):
        if parent_key in self.udb_episode_dict:
            self.udb_episode_dict[parent_key].update(child_dict)
        else:
            self.udb_episode_dict[parent_key] = child_dict
        self.logger.debug(f'Updated udb dict: {self.udb_episode_dict}')

    def _get_udb_dict(self):
        return self.udb_episode_dict

    @retry()
    def _send_request(self, url, referer=None, extra_headers=None, cookies={}, return_type='text'):
        '''
        call response session and return response
        Argument: return_type - valid options are text/json/bytes
        '''
        # print(f'{self.req_session}: {url}')
        header = self.header
        if referer: header.update({'referer': referer})
        if extra_headers: header.update(extra_headers)
        if return_type.lower() == 'json': header.update({'accept': 'application/json, text/javascript'})
        response = self.req_session.get(url, timeout=self.request_timeout, headers=header, cookies=cookies, verify=False)
        # print(response)
        if response.status_code == 200:
            if return_type.lower() == 'text':
                return response.text
            elif return_type.lower() == 'bytes':
                return response.content
            elif return_type.lower() == 'json':
                return response.json()
        else:
            self.logger.error(f'Failed with response code: {response.status_code}')

    def _get_bsoup(self, search_url, referer=None, extra_headers=None, cookies={}):
        '''
        return html parsed soup
        '''
        html_content = self._send_request(search_url, referer, extra_headers, cookies, 'text')

        return BS(html_content, 'html.parser')

    def _exec_cmd(self, cmd):
        proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
        # print stdout to console
        msg = proc.communicate()[0].decode("utf-8")
        std_err = proc.communicate()[1].decode("utf-8")
        rc = proc.returncode
        if rc != 0:
            raise Exception(f"Error occured: {std_err}")
        return msg

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

    # step-4.1 -- used in GogoAnime, MyAsianTV
    def _get_stream_link(self, link, stream_links_element):
        '''
        return stream link for extracting download links
        '''
        self.logger.debug(f'Extract stream link from soup for {link = }')
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        for stream in soup.select(stream_links_element):
            if 'active' in stream.get('class'):
                stream_link = stream['data-video']
                if stream_link.startswith('/'):
                    stream_link = 'https:' + stream_link
                return stream_link

    # step-4.2.1 -- used in GogoAnime, MyAsianTV
    def _parse_m3u8_links(self, master_m3u8_link, referer):
        '''
        parse master m3u8 data and return dict of resolutions and m3u8 links
        '''
        m3u8_links = {}
        base_url = '/'.join(master_m3u8_link.split('/')[:-1])
        self.logger.debug(f'Extracting m3u8 data from master link: {master_m3u8_link}')
        master_m3u8_data = self._send_request(master_m3u8_link, referer)
        # self.logger.debug(f'{master_m3u8_data = }')

        _regex_list = lambda data, rgx, grp: [ url.group(grp) for url in re.finditer(rgx, data) ]
        resolutions = _regex_list(master_m3u8_data, 'RESOLUTION=(.*),', 1)
        resolution_names = _regex_list(master_m3u8_data, 'NAME="(.*)"', 1)
        resolution_links = _regex_list(master_m3u8_data, '(.*)m3u8', 0)

        for _res, _pixels, _link in zip(resolution_names, resolutions, resolution_links):
            # prepend base url if it is relative url
            m3u8_link = _link if _link.startswith('http') else base_url + '/' + _link
            m3u8_links[_res.replace('p','')] = {
                'resolution_size': _pixels,
                'downloadLink': m3u8_link,
                'downloadType': 'hls'
            }

        if len(m3u8_links) == 0:
            # check for original keyword in the link, or if '#EXT-X-ENDLIST' in m3u8 data
            master_is_child = re.search('#EXT-X-ENDLIST', master_m3u8_data)
            if 'original' in master_m3u8_link or master_is_child:
                self.logger.debug('master m3u8 link itself is the download link')
                m3u8_links['1080'] = {                            # set resolution size to 1080 (assuming it as default. could be wrong)
                    'resolution_size': 'Original (HD)',
                    'downloadLink': master_m3u8_link,
                    'downloadType': 'hls'
                }

        return m3u8_links

    # step-4.2 -- used in GogoAnime, MyAsianTV
    def _get_download_links(self, **gdl_config):
        '''
        retrieve download links from stream link and return available resolution links
        - Sort the resolutions in ascending order
        '''
        self.logger.debug(f'Received get download links config: {gdl_config = }')

        # unpack configuration dictionary
        link = gdl_config['link']
        encrypted_url_args_regex = gdl_config['encrypted_url_args_regex']
        download_fetch_link = gdl_config['download_fetch_link']
        preferred_urls = gdl_config['preferred_urls']
        blacklist_urls = gdl_config['blacklist_urls']

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
            encrypted_response = self._send_request(dl_sources_link, link, {'x-requested-with': 'XMLHttpRequest'}, return_type='json')['data']
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
            dlink = download_link.get('file')
            dtype = download_link.get('type', '').strip().lower()

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
                    self.logger.warning(f'Failed to fetch m3u8 links from {dlink = }. Trying with alternative...')
                    if counter >= len(ordered_download_links):
                        self.logger.warning('No other alternatives found')

            elif dtype == 'mp4':
                # if link is mp4, it is a direct download link
                self.logger.debug(f'Found mp4 link. Adding the direct download link [{dlink}]')
                resltn = download_link.get('label', 'unknown').split()[0]
                resolution_links[resltn] = {
                    'resolution_size': resltn,
                    'downloadLink': dlink,
                    'downloadType': 'mp4'
                }

            else:
                # unknown download type
                self.logger.warning(f'Unknown download type [{dtype}] for link [{dlink}]')

        if resolution_links:      # sort the resolutions in ascending order
            resolution_links = dict(sorted(resolution_links.items(), key=lambda x: int(x[0])))

        self.logger.debug(f'Sorted resolution links: {resolution_links = }')

        return resolution_links

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

    def _get_episode_range_to_show(self, start, end, predefined_range=None, threshold=24):
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
            show_range = input(f'Enter range to display (ex: 1-16) [default={default_range}]: ') or 'all'
            if show_range.lower() == 'all':
                show_range = default_range

        try:
            start, end = map(int, map(float, show_range.split('-')))
        except ValueError as ve:
            start = end = int(float(show_range))
        except Exception as e:
            pass    # show all episodes

        if show_range == default_range:
            print('Showing all episodes:')
        else:
            print(f'Showing episodes from {start} to {end}:')

        return start, end

    def _resolution_selector(self, available_resolutions, target_resolution, selector_strategy='lowest'):
        '''
        Select a resolution based on selection strategy
        '''
        if 'error' in available_resolutions:
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
