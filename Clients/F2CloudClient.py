import base64
import json
import re
from typing import Union
from urllib.parse import unquote

from Clients.BaseClient import BaseClient


class F2CloudClient(BaseClient):
    '''
    Client to extract download source links for F2Cloud (formerly VidPlay). Credits: https://github.com/Ciarands/vidsrc-to-resolver
    '''
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://vid2v11.site')
        self.keys_url = config.get('keys_url', 'https://github.com/Ciarands/vidsrc-keys/blob/main/keys.json')
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'F2Cloud client initialized with {config = }')
        # Format the keys url to make it dynamic for using PRs. Replace main branch with {commit_id}
        default_commit_id = self.keys_url.split('/')[-2]
        self.keys_url = '/'.join(self.keys_url.split('/')[:-2] + ['{commit_id}', self.keys_url.split('/')[-1]])
        self.logger.debug(f'Using generalized keys_url = {self.keys_url}, commit_id = {default_commit_id}')
        self.KEYS = self._get_keys(default_commit_id)

    ### Helper functions - START ###
    def _get_keys(self, commit_id: str = 'main') -> bool:
        try:
            # Extract keys from External Git Repo
            keys_url = self.keys_url.format(commit_id=commit_id)
            self.logger.debug(f'Fetching keys from external git source [Commit: {commit_id}], url: {keys_url}')
            resp = self._send_request(keys_url, return_type='json')['payload']['blob']['rawLines'][0]
            self.logger.debug(f'Fetched keys from {keys_url} are: {resp}')
            return json.loads(resp)
        except Exception as e:
            self.logger.warning(f'No keys found for commit id: {commit_id}')
            return {}

    def _get_key(self, enc: bool, idx: int) -> str:
        return self.KEYS["encrypt" if enc else "decrypt"][idx]

    def _decode_base64_url_safe(self, s: str) -> bytearray:
        standardized_input = s.replace('_', '/').replace('-', '+')
        binary_data = base64.b64decode(standardized_input)
        return bytearray(binary_data)

    def _decode_data(self, key: str, data: Union[bytearray, str]) -> bytearray:
        self.logger.debug(f'Decoding {data = } using {key = }')
        key_bytes = bytes(key, 'utf-8')
        s = bytearray(range(256))
        j = 0

        for i in range(256):
            j = (j + s[i] + key_bytes[i % len(key_bytes)]) & 0xff
            s[i], s[j] = s[j], s[i]

        decoded = bytearray(len(data))
        i, k = 0, 0

        for index in range(len(data)):
            i = (i + 1) & 0xff
            k = (k + s[i]) & 0xff
            s[i], s[k] = s[k], s[i]
            t = (s[i] + s[k]) & 0xff

            if isinstance(data[index], str):
                decoded[index] = ord(data[index]) ^ s[t]
            elif isinstance(data[index], int):
                decoded[index] = data[index] ^ s[t]
            else:
                self.logger.warning("Unsupported data type in the input for decoding")
                return

        return decoded

    def _encode_data(self, key: str, data: str) -> str:
        self.logger.debug(f'Encoding {data = } using {key = }')
        decoded_id = self._decode_data(key, data)

        encoded_base64 = base64.b64encode(decoded_id)
        decoded_result = encoded_base64.decode("utf-8")

        return decoded_result.replace("/", "_").replace("+", "-")
    ### Helper functions - END ###

    # step-4.2
    def _get_f2cloud_link(self, src_url):
        '''
        extract the F2Cloud link
        '''
        # Extract F2Cloud source url
        self.logger.debug(f'Fetching F2Cloud link [{src_url}]')
        resp = self._send_request(src_url, return_type='json')
        src_url_encrypted = resp.get('result', {}).get('url')
        self.logger.debug(f'Extracted F2Cloud link (encoded): {src_url_encrypted}')
        if src_url_encrypted is None:
            return

        # Decode extracted F2Cloud url
        try:
            decode_key = self._get_key(False, 0)
            self.logger.debug(f'Decoding F2Cloud url with decode key: {decode_key}')
            src_url_encoded = self._decode_base64_url_safe(src_url_encrypted)
            src_url_decoded_raw = self._decode_data(decode_key, src_url_encoded)
            src_url_decoded = unquote(src_url_decoded_raw.decode('utf-8'))
            self.logger.debug(f'Decoded F2Cloud url: {src_url_decoded}')
            return src_url_decoded

        except Exception as e:
            self.logger.warning(f'Error decoding F2Cloud url: {e}')
            return

    # step-4.3
    def _get_provider_subtitles(self, url_data: str):
        '''
        Extract dict of available subtitles
        '''
        self.logger.debug('Fetching video subtitles')
        subtitles = {}
        try:
            subtitles_url = re.search(r"info=([^&]+)", url_data)

            subtitles_url_formatted = unquote(subtitles_url.group(1))
            resp = self._send_request(subtitles_url_formatted, return_type='json')
            self.logger.debug(f'Fetched subtitles raw response: {resp}')

            subtitles = { subtitle.get("label"): subtitle.get("file") for subtitle in resp }

        except Exception as e:
            self.logger.warning('Failed to fetch subtitles or no subtitles found')

        self.logger.debug(f'Available subtitles: {subtitles}')
        return subtitles
 
    # step-4.4
    def _resolve_sources(self, url: str):
        '''
        resolve the download sources and return the list of download sources.
        '''
        self.logger.debug(f'Resolving sources for url [{url}]')
        url_data = url.split("?")

        # Encode embed id
        try:
            self.logger.debug('Extracting the encoding key required for embed_id...')
            embed_encryption_key = self._get_key(True, 1)
            embed_id = self._encode_data(embed_encryption_key, url_data[0].split("/e/")[-1])
            self.logger.debug(f'Extracted {embed_id = }')
        except Exception as e:
            return {'error': f'Failed to get embed_id. Error: {e}'}

        # Encode h id
        try:
            self.logger.debug('Extracting the encoding key required for h...')
            h_encryption_key = self._get_key(True, 2)
            h = self._encode_data(h_encryption_key, url_data[0].split("/e/")[-1])
            self.logger.debug(f'Extracted {h = }')
        except Exception as e:
            return {'error': f'Failed to get h. Error: {e}'}

        # Extract the download sources
        final_decoded_link = f"{self.base_url}/mediainfo/{embed_id}?{url_data[1]}&autostart=true&h={h}"
        self.logger.debug(f'Resolving download sources for F2Cloud [{final_decoded_link}]')
        req_data = self._send_request(final_decoded_link, referer=url, return_type='json')
        self.logger.debug(f'Download sources response: {req_data}')

        if req_data and req_data.get("result"):
            if str(req_data.get("result")).startswith('40'):
                self.logger.warning(f'Failed to fetch download sources with response code: {req_data.get("result")}. Probably keys expired!')
                return {'error': 'Invalid vidsrc keys'}
            else:
                # Decode the sources
                try:
                    sources_encoded = req_data.get("result")
                    final_decode_key = self._get_key(False, 1)
                    decoded_sources = unquote(self._decode_data(final_decode_key, self._decode_base64_url_safe(sources_encoded)).decode('utf-8'))
                    self.logger.debug(f'Decoded Download sources: {decoded_sources}')
                    sources = json.loads(decoded_sources).get('sources')
                    return sources
                except Exception as e:
                    return {'error': f'Failed to decode sources. Error: {e}'}

        return {'error': 'No download links found'}
