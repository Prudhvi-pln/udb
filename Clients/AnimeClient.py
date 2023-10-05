__author__ = 'Prudhvi PLN'

import json
import re
import jsbeautifier as js
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class AnimeClient(BaseClient):
    def __init__(self, config, session=None):
        super().__init__(config['request_timeout'], session)
        self.base_url = config['base_url']
        self.search_url = self.base_url + config['search_url']
        self.episodes_list_url = self.base_url + config['episodes_list_url']
        self.download_link_url = self.base_url + config['download_link_url']
        self.episode_url = self.base_url + config['episode_url']
        self.anime_id = ''      # anime id. required to create referer link
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.logger.debug(f'Anime client initialized with {config = }')

    def _show_search_results(self, key, details):
        '''
        pretty print anime results based on your search
        '''
        info = f"{key}: {details.get('title')} | {details.get('type')}\n   " + \
                f"| Episodes: {details.get('episodes')} | Released: {details.get('year')}, {details.get('season')} " + \
                f"| Status: {details.get('status')}"
        print(info)

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

        print(info)

    def _get_kwik_links(self, ep_id):
        '''
        [DEPRECATED] return json data containing kwik links for a episode
        '''
        response = self._send_request(self.download_link_url + ep_id, None, False)
        self.logger.debug(f'Response: {response}')

        return json.loads(response)['data']

    def _get_kwik_links_v2(self, ep_link):
        '''
        Scrapes html instead of api call as per site structure as on Feb 15, 2023.
        Return resolutions data containing kwik links for a episode and filtered on:
        - Audio: filter out english dubs
        - Codec: use AV1 codec if available, else use default. AV1 offers better compression
        - Sort the resolutions in ascending order (already sorted by default)
        '''
        self.logger.debug(f'Fetching soup to extract kwik links for {ep_link = }')
        response = self._get_bsoup(ep_link)
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

    def search(self, keyword):
        '''
        search for anime based on a keyword
        '''
        # url decode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key

        response = self._send_request(search_url)
        self.logger.debug(f'Raw {response = }')
        if response is not None:
            # add index to search results
            response = { idx+1:result for idx, result in enumerate(response) }
            self.logger.debug(f'Extracted {response = }')
            self.show_search_results(response)

        return response

    def fetch_episodes_list(self, target):
        '''
        fetch all available episodes list in the selected anime
        '''
        session = target.get('session')
        episodes_data = []
        self.anime_id = session
        list_episodes_url = self.episodes_list_url + session

        self.logger.debug(f'Fetching episodes list from {list_episodes_url = }')
        raw_data = json.loads(self._send_request(list_episodes_url, None, False))
        self.logger.debug(f'Response {raw_data = }')

        last_page = int(raw_data['last_page'])
        self.logger.debug(f'{last_page = }')
        # add first page's episodes
        episodes_data = raw_data['data']

        # if last page is not 1, get episodes from all pages
        if last_page > 1:
            for pgno in range(2, last_page+1):
                self.logger.debug(f'Found more than 1 pages. Fetching episodes from page-{pgno}')
                episodes_data.extend(self._send_request(f'{list_episodes_url}&page={pgno}'))

        return episodes_data

    def fetch_episode_links(self, episodes, ep_start, ep_end):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')

            if float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end:
                self.logger.debug(f'Processing {episode = }')
                episode_link = self.episode_url.replace('_anime_id_', self.anime_id).replace('_episode_id_', episode.get('session'))

                self.logger.debug(f'Fetching kwik link for {episode_link = }')
                links = self._get_kwik_links_v2(episode_link)
                self.logger.debug(f'Extracted & filtered (no eng dub & prefer AV1) kwik links: {links = }')

                if links is not None:
                    # add episode uid & link to udb dict
                    self._update_udb_dict(episode.get('episode'), {'episodeId': episode.get('session'), 'episodeLink': episode_link})

                    download_links[episode.get('episode')] = links
                    self._show_episode_links(episode.get('episode'), links)

        return download_links

    def set_out_names(self, target_series):
        anime_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = f"{anime_title} ({target_series['year']})"
        anime_type = 'movie' if target_series.get('type').lower() == 'movie' else 'episode'
        episode_prefix = f"{anime_title} {anime_type}"

        return target_dir, episode_prefix

    def get_m3u8_content(self, kwik_link, ep_no):
        '''
        return response as text of kwik link
        '''
        referer_link = self.udb_episode_dict[ep_no]['episodeLink']
        response = self._send_request(kwik_link, referer_link, False)

        return response

    def parse_m3u8_link(self, text):
        '''
        parse m3u8 link from raw response by executing the javascript code
        '''
        # if below logic is still failing, then execute the javascript code from html response
        # use either selenium in headless or use online compiler api (ex: https://onecompiler.com/javascript)
        # print(text)
        _regex_extract = lambda rgx, txt, grp: re.search(rgx, txt).group(grp) if re.search(rgx, txt) else False

        self.logger.debug('Extracting javascript code')
        js_code = _regex_extract(";eval\(.*\)", text, 0)
        if not js_code:
            raise Exception('m3u8 link extraction failed. js code not found')

        self.logger.debug('Executing javascript code')
        try:
            parsed_js_code = js.beautify(js_code.replace(';', '', 1))
        except Exception as e:
            raise Exception('m3u8 link extraction failed. Unable to execute js')

        self.logger.debug('Extracting m3u8 links')
        parsed_link = _regex_extract('http.*.m3u8', parsed_js_code, 0)
        if not parsed_link:
            raise Exception('m3u8 link extraction failed. link not found')

        return parsed_link

    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        _get_ep_name = lambda resltn: f"{episode_prefix}{' ' if episode_prefix.endswith('movie') and len(target_links.items()) <= 1 else f' {ep} '}- {resltn}P.mp4"

        for ep, link in target_links.items():
            error = None
            self.logger.debug(f'Epsiode: {ep}, Link: {link}')
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

                    # add m3u8 & kwik links against episode
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'refererLink': kwik_link, 'm3u8Link': ep_link})
                    self.logger.debug(f'{info} Link found [{ep_link}]')
                    print(f'{info} Link found [{ep_link}]')

                except Exception as e:
                    error = f'Failed to fetch link with error [{e}]'

            if error:
                # add error message and log it
                ep_name = _get_ep_name(resolution)
                self._update_udb_dict(ep, {'episodeName': ep_name, 'error': error})
                self.logger.error(f'{info} {error}')

        final_dict = { k:v for k,v in self._get_udb_dict().items() }

        return final_dict

    def show_episode_results(self, items, predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range, threshold=30)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                print(f"Episode: {self._safe_type_cast(item.get('episode'))} | Audio: {item.get('audio')} | Duration: {item.get('duration')} | Release date: {item.get('created_at')}")
