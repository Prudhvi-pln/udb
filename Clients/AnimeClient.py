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
        for _res in details:
            _reskey = next(iter(_res))
            filesize = _res[_reskey]['filesize']
            try:
                filesize = filesize / (1024**2)
                info += f' | {_reskey}P ({filesize:.2f} MB) [{_res[_reskey]["audio"]}]'
            except:
                info += f' | {filesize} [{_res[_reskey]["audio"]}]'

        print(info)

    def _get_kwik_links(self, ep_id):
        '''
        return json data containing kwik links for a episode
        '''
        response = self._send_request(self.download_link_url + ep_id, None, False)
        # print(response)

        return json.loads(response)['data']
    
    def _get_kwik_links_v2(self, ep_link):
        '''
        return json data containing kwik links for a episode. Scrapes html instead of api call as per site structure as on Feb 15, 2023
        '''
        response = self._get_bsoup(ep_link)
        # print(response)
        links = response.select('div#resolutionMenu button')
        sizes = response.select('div#pickDownload a')
        results = []
        for l,s in zip(links, sizes):
            res_dict = {}
            res = l['data-resolution']
            kwik = l['data-src']
            audio = l['data-audio']
            size = s.text.strip()
            res_dict[res] = {'kwik': kwik, 'audio': audio, 'filesize': size}
            results.append(res_dict)

        return results

    def search(self, keyword):
        '''
        search for anime based on a keyword
        '''
        # url decode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key

        response = self._send_request(search_url)
        if response is not None:
            # add index to search results
            response = { idx+1:result for idx, result in enumerate(response) }
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

        raw_data = json.loads(self._send_request(list_episodes_url, None, False))
        last_page = int(raw_data['last_page'])
        # add first page's episodes
        episodes_data = raw_data['data']
        # if last page is not 1, get episodes from all pages
        if last_page > 1:
            for pgno in range(2, last_page+1):
                episodes_data.extend(self._send_request(f'{list_episodes_url}&page={pgno}'))

        return episodes_data

    def fetch_episode_links(self, episodes, ep_start, ep_end):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        for episode in episodes:
            if float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end:
                episode_link = self.episode_url.replace('_anime_id_', self.anime_id).replace('_episode_id_', episode.get('session'))
                response = self._get_kwik_links_v2(episode_link)
                if response is not None:
                    # add episode uid & link to udb dict
                    self._update_udb_dict(episode.get('episode'), {'episodeId': episode.get('session'), 'episodeLink': episode_link})
                    # filter out eng dub links
                    links = [ _res for _res in response for k in _res.values() if k.get('audio') != 'eng']
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
        js_code = _regex_extract(";eval\(.*\)", text, 0)
        if not js_code:
            raise Exception('m3u8 link extraction failed. js code not found')

        try:
            parsed_js_code = js.beautify(js_code.replace(';', '', 1))
        except Exception as e:
            raise Exception('m3u8 link extraction failed. Unable to execute js')

        parsed_link = _regex_extract('http.*.m3u8', parsed_js_code, 0)
        if not parsed_link:
            raise Exception('m3u8 link extraction failed. link not found')

        return parsed_link

    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        has_key = lambda x, y: y in x.keys()

        for ep, link in target_links.items():
            print(f'Episode: {self._safe_type_cast(ep)}', end=' | ')
            res_dict = [ i.get(resolution) for i in link if has_key(i, resolution) ]
            if len(res_dict) == 0:
                print(f'Resolution [{resolution}] not found')
            else:
                try:
                    if episode_prefix.endswith('movie') and len(target_links.items()) <= 1:
                        ep_name = f'{episode_prefix} - {resolution}P.mp4'
                    else:
                        ep_name = f'{episode_prefix} {ep} - {resolution}P.mp4'
                    ep_name = self._windows_safe_string(ep_name)
                    kwik_link = res_dict[0]['kwik']
                    raw_content = self.get_m3u8_content(kwik_link, ep)
                    ep_link = self.parse_m3u8_link(raw_content)
                    # add m3u8 & kwik links against episode
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'refererLink': kwik_link, 'm3u8Link': ep_link})
                    print(f'Link found [{ep_link}]')
                except Exception as e:
                    print(f'Failed to fetch link with error [{e}]')

        final_dict = { k:v for k,v in self._get_udb_dict().items() if v.get('m3u8Link') is not None }
        # print(final_dict)

        return final_dict

    def show_search_results(self, items):
        '''
        print all anime results based on your search at once if required
        '''
        for idx, item in items.items():
            self._show_search_results(idx, item)

    def show_episode_results(self, items):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        cnt = show = len(items)
        if cnt > 30:
            show = int(input(f'Total {cnt} episodes found. Enter range to display [default=ALL]: ') or cnt)
            print(f'Showing top {show} episodes:')
        for item in items[:show]:
            print(f"Episode: {self._safe_type_cast(item.get('episode'))} | Audio: {item.get('audio')} | Duration: {item.get('duration')} | Release date: {item.get('created_at')}")

    def show_episode_links(self, items):
        '''
        print all episodes details at once if required
        '''
        for item, details in items.items():
            self._show_episode_links(item, details)
