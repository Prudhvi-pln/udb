import base64
import json
import re
from typing import Union
from urllib.parse import unquote

from Clients.BaseClient import BaseClient


class VidPlayClient(BaseClient):
    '''
    Client to extract download source links for VidPlay. Credits: https://github.com/Ciarands/vidsrc-to-resolver
    '''
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://vidplay.online')
        self.keys_url = config.get('keys_url', 'https://github.com/KillerDogeEmpire/vidplay-keys/blob/keys/keys.json')
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'VidPlay client initialized with {config = }')
        # Format the keys url to make it dynamic for using PRs. Replace main branch with {commit_id}
        self.default_commit_id = self.keys_url.split('/')[-2]
        self.keys_url = '/'.join(self.keys_url.split('/')[:-2] + ['{commit_id}', self.keys_url.split('/')[-1]])
        self.logger.debug(f'Using generalized keys_url = {self.keys_url}, commit_id = {self.default_commit_id}')

    # step-4.2
    def _get_vidplay_link(self, vidplay_src_url, vidsrc_key):
        '''
        extract the vidplay link
        '''
        # extract vidplay source url
        self.logger.debug(f'Fetching vidplay link [{vidplay_src_url}]')
        resp = self._send_request(vidplay_src_url, return_type='json')
        vidplay_url_encrypted = resp['result'].get('url')
        self.logger.debug(f'Extracted vidplay link (encoded): {vidplay_url_encrypted}')
        if vidplay_url_encrypted is None:
            return

        # decode extracted vidplay url
        self.logger.debug('Decoding vidplay url')
        try:
            vidplay_url_standardized = vidplay_url_encrypted.replace('_', '/').replace('-', '+')
            vidplay_url_binary = base64.b64decode(vidplay_url_standardized)
            vidplay_url_encoded = bytearray(vidplay_url_binary)
            vidplay_url_decoded_raw = self._decode_data(vidsrc_key, vidplay_url_encoded)
            vidplay_url_decoded = unquote(vidplay_url_decoded_raw.decode('utf-8'))
            self.logger.debug(f'Decoded vidplay url: {vidplay_url_decoded}')
        except Exception as e:
            self.logger.warning(f'Error decoding vidplay url: {e}')
            return

        return vidplay_url_decoded

    # step-4.2.1
    def _decode_data(self, key: str, data: Union[bytearray, str]) -> bytearray:
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

    # step-4.4.1
    def _encode_data(self, v_id: str, key1: str, key2: str) -> str:
        decoded_id = self._decode_data(key1, v_id)
        encoded_result = self._decode_data(key2, decoded_id)

        encoded_base64 = base64.b64encode(encoded_result)
        decoded_result = encoded_base64.decode("utf-8")

        return decoded_result.replace("/", "_")

    # step-4.4.2
    def _get_futoken(self, key: str, url: str):
        '''
        Extract Futoken and decode the key
        '''
        self.logger.debug('Extract Futoken...')
        resp = self._send_request(f"{self.base_url}/futoken", referer=url)
        fu_key = re.search(r"var\s+k\s*=\s*'([^']+)'", resp).group(1)
        self.logger.debug(f'Extracted Futoken: {fu_key}')

        self.logger.debug(f'Decoding Futoken key using key: {key}')
        fu_key = f"{fu_key},{','.join([str(ord(fu_key[i % len(fu_key)]) + ord(key[i])) for i in range(len(key))])}"
        self.logger.debug(f'Decoded Futoken key: {fu_key}')

        return fu_key

    # step-4.3
    def _get_vidplay_subtitles(self, url_data: str):
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
 
    # step-4.4.1
    def _resolve_sources_inner(self, url: str, commit_id: str = 'main'):
        '''
        resolve the download sources and return the list of download sources using given repo commit id.
        '''
        self.logger.debug(f'Resolving sources for url [{url}] using commit id: {commit_id}')
        url_data = url.split("?")

        try:
            # Extract keys from External Git Repo
            keys_url = self.keys_url.format(commit_id=commit_id)
            self.logger.debug(f'Fetching keys from external git source [Commit: {commit_id}], url: {keys_url}')
            resp = self._send_request(keys_url, return_type='json')['payload']['blob']['rawLines'][0]
            self.logger.debug(f'Fetched keys from {keys_url} are: {resp}')
            key1, key2 = json.loads(resp)
        except Exception as e:
            self.logger.warning(f'No keys found for commit id: {commit_id}')
            return {'error': 'vidsrc keys not found'}

        try:
            # encode key required for futoken
            self.logger.debug('Extracting the encoding key required for futoken...')
            key = self._encode_data(url_data[0].split("/e/")[-1], key1, key2)
            self.logger.debug(f'Extracted encoding key for futoken: {key}')
        except Exception as e:
            return {'error': f'Failed to encode key. Error: {e}'}

        try:
            # get futoken key from futoken api
            futoken = self._get_futoken(key, url)
        except Exception as e:
            return {'error': f'Failed to extract futoken key. Error: {e}'}

        # extract the download sources
        vidplay_decoded_link = f"{self.base_url}/mediainfo/{futoken}?{url_data[1]}&autostart=true"
        self.logger.debug(f'Resolving download sources for Vidplay [{vidplay_decoded_link}]')
        req_data = self._send_request(vidplay_decoded_link, referer=url, return_type='json')
        self.logger.debug(f'Download sources response: {req_data}')

        if req_data and req_data.get("result"):
            if type(req_data.get("result")) == dict:
                sources = req_data.get("result").get("sources")
                self.logger.debug(f'Download sources: {sources}')
                return sources
            elif req_data.get("result") == 404:
                self.logger.warning('Failed to fetch download sources with response code: 404. Probably keys expired!')
                return {'error': 'Invalid vidsrc keys'}

        return {'error': 'No download links found'}

    # step-4.4
    def _resolve_sources(self, url: str):
        '''
        resolve the download sources and return the list of download sources.
        '''
        self.logger.debug(f'Start resolving sources using recursive approach')

        # Resolving resources. Use default branch first
        response = self._resolve_sources_inner(url, commit_id=self.default_commit_id)
        if not ('error' in response and 'vidsrc keys' in response.get('error')):
            return response

        self.logger.debug('Looking for vidsrc keys in alternate commits')

        # idea is to look for vidsrc keys in the pull requests. Becoz even if owner is inactive, community is active :)
        keys_base_url = '/'.join(self.keys_url.split('/')[:-3])
        pull_soup = self._get_bsoup(f'{keys_base_url}/pulls', extra_headers={'Accept': 'text/html, application/xhtml+xml'}, silent=True)

        available_prs = [ i['href'].split('/')[-1] for i in pull_soup.select('div a') if i.get('data-hovercard-type') == 'pull_request' ]
        self.logger.debug(f'Available Pull Requests for Vidsrc keys: {available_prs}')

        for pr in available_prs:
            pr_url = f'{keys_base_url}/pull/{pr}/files'
            try:
                self.logger.debug(f'Extracting commit id from: {pr_url}')
                soup = self._get_bsoup(f'{pr_url}', silent=True)
                commit_id = [ i.get('data-commit') for i in soup.select('a.select-menu-item') if i.get('data-commit') ][0]
                self.logger.debug(f'Extracted commit id: {commit_id}')
                self.logger.info(f'Retrying to resolve sources with commit id: {commit_id}')
                # Resolving resources. Use other alternatives.
                response = self._resolve_sources_inner(url, commit_id=commit_id)
                if not ('error' in response and 'vidsrc keys' in response.get('error')):
                    return response
            except Exception as e:
                self.logger.debug(f'Failed to fetch commit id with error: {e}')

        else:
            self.logger.info('No other sources found for vidsrc keys!')

        return response
