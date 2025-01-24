__author__ = 'Prudhvi PLN'

import json
import re
from urllib.parse import quote_plus

# modules to bypass DDoS protection
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from time import sleep

from Clients.BaseClient import BaseClient


class AnimePaheClient(BaseClient):
    '''
    Anime Client for AnimePahe site
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://animepahe.ru/')
        self.search_url = self.base_url + config.get('search_url', 'api?m=search&q=')
        self.episodes_list_url = self.base_url + config.get('episodes_list_url', 'api?m=release&sort=episode_asc&id=')
        self.download_link_url = self.base_url + config.get('download_link_url', 'api?m=links&p=kwik&id=')
        self.episode_url = self.base_url + config.get('episode_url', 'play/{anime_id}/{episode_id}')
        self.anime_id = ''      # anime id. required to create referer link
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'AnimePahe client initialized with {config = }')

    # step-1.1.1
    def _get_new_cookies(self, url, check_condition, max_retries=3, wait_time_in_secs=5):
        '''
        Extract new cookies required for authentication to By-pass DDoS protection.
        Returns a dictionary of cookies
        '''
        driver = self._get_undetected_chrome_driver(client='AnimePaheClient')
        driver.get(url)

        retry_cnt = 1
        while retry_cnt <= max_retries:
            try:
                self.logger.debug('Checking if site is loaded...')
                driver.find_element(By.XPATH, check_condition)
                break
            except NoSuchElementException as nsee:
                self.logger.debug(f'Site not loaded! Waiting for DDoS check to complete. Retry count: {retry_cnt} / {max_retries}')
                retry_cnt += 1
                sleep(wait_time_in_secs)

        if retry_cnt > max_retries:
            driver.quit()
            raise Exception(f'Failed to load site within {max_retries*wait_time_in_secs} seconds')
        else:
            self.logger.debug('Site loaded successfully! Extracting cookies...')
            all_cookies = driver.get_cookies()
            driver.close()
            driver.quit()

        cookies = {}
        for cookie in all_cookies:
            cookies[cookie['name']] = cookie['value']

        return cookies

    # step-1.1
    def _get_site_cookies(self, url):
        '''
        Load cookies required for authentication. Required to By-pass DDoS protection.
        Returns a dictionary of cookies
        '''
        cookies = self._load_udb_cookies(client='animepahe')

        if cookies:
            # Check if cookies are valid
            self.logger.debug(f'Validating reloaded cookies: {cookies}')
            resp = self._send_request(url, cookies=cookies)
            if resp is None:
                self.logger.error('Cookies expired. Loading new cookies...')
            else:
                return cookies

        # Load new cookies
        cookies = self._get_new_cookies(url, '/html/body/header/nav/a/img')
        self._save_udb_cookies(client='animepahe', data=cookies)

        return cookies

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print anime results based on your search
        '''
        info = f"{key}: {details.get('title')} | {details.get('type')}\n   " + \
                f"| Episodes: {details.get('episodes')} | Released: {details.get('year')}, {details.get('season')} " + \
                f"| Status: {details.get('status')}"
        self._colprint('results', info)

    # step-4.1 - obsolete
    def _get_kwik_links(self, ep_id):
        '''
        [DEPRECATED] return json data containing kwik links for a episode
        '''
        response = self._send_request(self.download_link_url + ep_id, cookies=self.cookies, return_type='text')
        self.logger.debug(f'Response: {response}')

        return json.loads(response)['data']

    # step-4.1
    def _get_kwik_links_v2(self, ep_link):
        '''
        Scrapes html instead of api call as per site structure as on Feb 15, 2023.
        Return resolutions data containing kwik links for a episode and filtered on:
        - Audio: filter out english dubs
        - Codec: use AV1 codec if available, else use default. AV1 offers better compression
        - Sort the resolutions in ascending order (already sorted by default)
        '''
        self.logger.debug(f'Fetching soup to extract kwik links for {ep_link = }')
        response = self._get_bsoup(ep_link, cookies=self.cookies)
        # self.logger.debug(f'bsoup response for {ep_link = }: {response}')

        links = response.select('div#resolutionMenu button')
        self.logger.debug(f'Extracted {links = }')
        sizes = response.select('div#pickDownload a')
        self.logger.debug(f'Extracted {sizes = }')

        resolutions = {}
        for l,s in zip(links, sizes):
            resltn = l['data-resolution']
            current_audio = l['data-audio']
            current_codec = l['data-av1']
            # add new resolution & update a resolution only if current_codec is 1 (AV1). Preference: 1 > 0 > others
            if resltn in resolutions and current_codec != '1':
                continue
            # skip english dubs
            if current_audio == 'eng':
                continue
            resolutions[resltn] = {
                'kwik': l['data-src'],
                'audio': current_audio,
                'codec': current_codec,
                'filesize': s.text.strip()
            }

        # if resolutions:   # sort the resolutions in ascending order
        #     resolutions = dict(sorted(resolutions.items(), key=lambda x: int(x[0])))

        return resolutions

    # step-4.2
    def _show_episode_links(self, key, details):
        '''
        pretty print episode links from fetch_episode_links
        '''
        info = f"Episode: {self._safe_type_cast(key)}"
        for _res, _vals in details.items():
            filesize = _vals['filesize']
            try:
                filesize = filesize / (1024**2)
                info += f' | {_res}P ({filesize:.2f} MB) [{_vals["audio"]}]'
            except:
                info += f' | {filesize} [{_vals["audio"]}]'

        self._colprint('results', info)

    # step-6.1
    def get_m3u8_content(self, kwik_link, ep_no):
        '''
        return response as text of kwik link
        '''
        referer_link = self.udb_episode_dict[ep_no]['episodeLink']
        response = self._send_request(kwik_link, referer=referer_link)

        return response

    # step-6.2
    def parse_m3u8_link(self, text):
        '''
        parse m3u8 link using javascript's packed function implementation
        '''
        self.logger.debug('Extracting packed args from javascript code')
        x = r"\}\('(.*)'\)*,*(\d+)*,*(\d+)*,*'((?:[^'\\]|\\.)*)'\.split\('\|'\)*,*(\d+)*,*(\{\})"
        try:
            p, a, c, k, e, d = re.findall(x, text)[0]
            p, a, c, k, e, d = p, int(a), int(c), k.split('|'), int(e), {}
        except Exception as e:
            raise Exception('m3u8 link extraction failed. Unable to extract packed args')

        def e(c):
            x = '' if c < a else e(int(c/a))
            c = c % a
            return x + (chr(c + 29) if c > 35 else '0123456789abcdefghijklmnopqrstuvwxyz'[c])

        self.logger.debug('Unpacking extracted packed args')
        for i in range(c): d[e(i)] = k[i] or e(i)
        parsed_js_code = re.sub(r'\b(\w+)\b', lambda e: d.get(e.group(0)) or e.group(0), p)

        self.logger.debug('Extracting m3u8 link from unpacked javascript code')
        parsed_link = self._regex_extract('http.*.m3u8', parsed_js_code, 0)
        if not parsed_link:
            raise Exception('m3u8 link extraction failed. link not found')

        return parsed_link

    # step-1
    def search(self, keyword, search_limit=10):
        '''
        search for anime based on a keyword
        '''
        # Note: As on Jan-16, 2024, animepahe uses DDoS Guard. Load cookies generated by DDoS check.
        self.cookies = self._get_site_cookies(self.base_url)

        # url encode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key

        response = self._send_request(search_url, cookies=self.cookies, return_type='json')
        self.logger.debug(f'Raw {response = }')
        response = response['data'] if response['total'] > 0 else None
        if response is not None:
            # add index to search results. Search limit need not be applied, as the results are already fetched via single request
            response = { idx+1:result for idx, result in enumerate(response) }
            self.logger.debug(f'Extracted {response = }')
            # display search results
            for idx, item in response.items():
                self._show_search_results(idx, item)

        return response

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch all available episodes list in the selected anime
        '''
        session = target.get('session')
        episodes_data = []
        self.anime_id = session
        list_episodes_url = self.episodes_list_url + session

        self.logger.debug(f'Fetching episodes list from {list_episodes_url = }')
        raw_data = self._send_request(list_episodes_url, cookies=self.cookies, return_type='json')
        self.logger.debug(f'Response {raw_data = }')

        last_page = int(raw_data['last_page'])
        self.logger.debug(f'{last_page = }')
        # add first page's episodes
        episodes_data = raw_data['data']

        # if last page is not 1, get episodes from all pages
        if last_page > 1:
            for pgno in range(2, last_page+1):
                self.logger.debug(f'Found more than 1 pages. Fetching episodes from page-{pgno}')
                episodes_data.extend(self._send_request(f'{list_episodes_url}&page={pgno}', cookies=self.cookies, return_type='json').get('data', []))

        return episodes_data

    # step-3
    def show_episode_results(self, items, *predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range[1], threshold=30)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                self._colprint('results', f"Episode: {self._safe_type_cast(item.get('episode'))} | Audio: {item.get('audio')} | Duration: {item.get('duration')} | Release date: {item.get('created_at')}")

    # step-4
    def fetch_episode_links(self, episodes, ep_ranges):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        ep_start, ep_end, specific_eps = ep_ranges['start'], ep_ranges['end'], ep_ranges.get('specific_no', [])

        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')

            if (float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end) or (float(episode.get('episode')) in specific_eps):
                self.logger.debug(f'Processing {episode = }')
                episode_link = self.episode_url.format(anime_id=self.anime_id, episode_id=episode.get('session'))

                self.logger.debug(f'Fetching kwik link for {episode_link = }')
                links = self._get_kwik_links_v2(episode_link)
                self.logger.debug(f'Extracted & filtered (no eng dub & prefer AV1) kwik links: {links = }')

                # skip if no links found
                if links is None:
                    continue

                # add episode uid & link to udb dict
                self._update_udb_dict(episode.get('episode'), {'episodeId': episode.get('session'), 'episodeLink': episode_link})

                download_links[episode.get('episode')] = links
                self._show_episode_links(episode.get('episode'), links)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        anime_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = f"{anime_title} ({target_series['year']})"
        anime_type = 'Movie' if target_series.get('type').lower() == 'movie' else 'Episode'
        episode_prefix = f"{anime_title} {anime_type}"

        return target_dir, episode_prefix

    # step-6
    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        _get_ep_name = lambda resltn: f"{episode_prefix}{' ' if episode_prefix.lower().endswith('movie') and len(target_links.items()) <= 1 else f' {ep} '}- {resltn}P.mp4"

        for ep, link in target_links.items():
            error = None
            self.logger.debug(f'Episode: {ep}, Link: {link}')
            info = f'Episode: {self._safe_type_cast(ep)} |'

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
                    ep_name = self._windows_safe_string(ep_name)
                    kwik_link = res_dict['kwik']

                    self.logger.debug(f'Fetching m3u8 content from {kwik_link = }')
                    raw_content = self.get_m3u8_content(kwik_link, ep)

                    self.logger.debug(f'Parsing m3u8 content from extracted')
                    ep_link = self.parse_m3u8_link(raw_content)
                    self.logger.debug(f'Extracted & Parsed {ep_link = }')

                    # add m3u8 & kwik links against episode. set type of download link as hls
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'refererLink': kwik_link, 'downloadLink': ep_link, 'downloadType': 'hls'})
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
