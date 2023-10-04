__author__ = 'Prudhvi PLN'

import json
import logging
import requests
from bs4 import BeautifulSoup as BS
from requests.adapters import HTTPAdapter
from subprocess import Popen, PIPE
from urllib3.util.retry import Retry
# import cloudscraper as cs
import base64
import binascii
from Crypto.Cipher import AES

from Utils.commons import retry


class BaseClient():
    def __init__(self, request_timeout=30, session=None):
        # create a requests session and use across to re-use cookies
        self.req_session = session if session else requests.Session()
        self.request_timeout = request_timeout
        # add retries with backoff
        retry = Retry(total=3, backoff_factor=0.1)
        adapter = HTTPAdapter(max_retries=retry)
        self.req_session.mount('http://', adapter)
        self.req_session.mount('https://', adapter)
        # disable insecure warnings
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
        # self.req_session = session if session else cs.create_scraper()
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
    def _send_request(self, url, referer=None, decode_json=True, extra_headers=None):
        '''
        call response session and return response
        '''
        # print(f'{self.req_session}: {url}')
        header = self.header
        if referer: header.update({'referer': referer})
        if extra_headers: header.update(extra_headers)
        response = self.req_session.get(url, headers=header, verify=False)
        # print(response)
        if response.status_code == 200:
            if not decode_json:
                return response.text
            data = json.loads(response.text)
            if data['total'] > 0:
                return data['data']
        else:
            self.logger.error(f'Failed with response code: {response.status_code}')

    def _get_bsoup(self, search_url, referer=None, extra_headers=None):
        '''
        return html parsed soup
        '''
        html_content = self._send_request(search_url, referer, False, extra_headers)

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

    def _get_cipher(self, key, iv):
        '''
        return the cipher based on given encryption key and initialization vector
        '''
        key = binascii.unhexlify(key)
        iv = binascii.unhexlify(iv)
        # set up the AES cipher in CBC mode with PKCS#7 padding
        cipher = AES.new(key, AES.MODE_CBC, iv)

        return cipher

    def _pad(self, s):
        return s + (self.bs - len(s) % self.bs) * chr(self.bs - len(s) % self.bs)

    def _unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def _encrypt(self, word, cipher):
        # [deprecated] using openssl
        # cmd = f'echo {word} | "{openssl_executable}" enc -aes256 -K {key} -iv {iv} -a -e'
        # Encrypt the message and add PKCS#7 padding
        padded_message = self._pad(word)
        encrypted_message = cipher.encrypt(padded_message.encode('utf-8'))
        # Base64-encode the encrypted message
        base64_encrypted_message = base64.b64encode(encrypted_message).decode('utf-8')

        return base64_encrypted_message

    def _decrypt(self, word, cipher):
        # [deprecated] using openssl
        # Decode the base64-encoded message
        # cmd = f'echo {word} | python -m base64 -d | "{openssl_executable}" enc -aes256 -K {key} -iv {iv} -d'
        encrypted_msg = base64.b64decode(word)
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
        if target_resolution in available_resolutions:
            return target_resolution

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

    def show_search_results(self, items):
        '''
        print all search results at once if required
        '''
        for idx, item in items.items():
            # below _show_search_results should be implemented in respective Client class
            self._show_search_results(idx, item)

    def show_episode_links(self, items):
        '''
        print all episodes details at once if required
        '''
        for item, details in items.items():
            # below _show_episode_links should be implemented in respective Client class
            self._show_episode_links(item, details)
