__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class DramaClient(BaseClient):
    '''
    Drama Client for MyAsianTV site
    '''
    # step-0
    def __init__(self, config, session=None):
        super().__init__(config['request_timeout'], session)
        self.base_url = config['base_url']
        self.search_url = self.base_url + config['search_url']
        self.episodes_list_url = self.base_url + config['episodes_list_url']
        self.search_link_element = config['search_link_element']
        self.search_title_element = config['search_title_element']
        self.series_info_element = config['series_info_element']
        self.episode_link_element = config['episode_link_element']
        self.episode_sub_type_element = config['episode_sub_type_element']
        self.episode_upload_time_element = config['episode_upload_time_element']
        self.stream_links_element = config['stream_links_element']
        self.download_fetch_link = config['download_fetch_link']
        self.preferred_urls = config['preferred_urls'] if config['preferred_urls'] else []
        self.blacklist_urls = config['blacklist_urls'] if config['blacklist_urls'] else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.logger.debug(f'Drama client initialized with {config = }')
        # regex to fetch the encrypted url args required to fetch master m3u8 / download links
        self.ENCRYPTED_URL_ARGS_REGEX = re.compile(rb'data-value="(.+?)"')
        # key & iv for decryption & encrytion. Not sure how these are fetched :(
        # Reference: https://github.com/CoolnsX/dra-cla/blob/main/dra-cla
        self.__key = b'93422192433952489752342908585752'
        self.__iv = b'9262859232435825'

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of a drama
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        for detail in soup.select(self.series_info_element):
            line = detail.text.strip()
            if ':' in line:
                meta[line.split(':')[0].strip()] = line.split(':')[1].strip().split('\n')[0]

        # get last episode number
        last_ep_no = soup.select_one(self.episode_link_element).text.strip().split()[-1]
        # if series is ongoing, get expected no of total episodes. works only for dramas where meta is available
        if meta['Status'].lower() != 'completed':
            try:
                match = re.search('Episodes:(.*)', soup.select('.info')[0].text)
                last_ep_no = f"{last_ep_no}+{'/' + match.group(1).strip() if match else ''}"
            except:
                last_ep_no = f'{last_ep_no}+'

        meta['Episodes'] = last_ep_no

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print drama results based on your search
        '''
        line = f"{key}: {details.get('title')} | Country: {details.get('Country')} | Genre: {details.get('Genre')}" + \
                f"\n   | Episodes: {details.get('Episodes', 'NA')} | Released: {details.get('year')} | Status: {details.get('Status')}"
        self._colprint('results', line)

    # step-2.1
    def _get_episodes_list(self, soup, ajax=False):
        '''Extract episodes and return as a list'''
        episode_list = []
        # if request is ajax, then use shortened css path, i.e., excluding 'ul'
        shortened_css = lambda x: ' '.join(x.split(' ')[1:]) if ajax else x

        sub_types = soup.select(shortened_css(self.episode_sub_type_element))
        upload_times = soup.select(shortened_css(self.episode_upload_time_element))
        links = soup.select(shortened_css(self.episode_link_element))

        # get episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')
        for sub_typ, upload_time, link in zip(sub_types, upload_times, links):
            ep_link = link['href']
            if ep_link.startswith('/'):
                ep_link = self.base_url + ep_link
            ep_name = link.text.strip()
            ep_no = ep_name.split()[-1]
            ep_no = float(ep_no) if '.' in ep_no else int(ep_no)
            ep_upload_time = upload_time.text.strip()
            ep_sub_typ = sub_typ['src'].split('/')[-1].split('.')[0].capitalize()
            episode_list.append({
                'episode': ep_no,
                'episodeName': self._windows_safe_string(ep_name),
                'episodeLink': ep_link,
                'episodeSubs': ep_sub_typ,
                'episodeUploadTime': ep_upload_time
            })

        return episode_list

    # step-4.3
    def _show_episode_links(self, key, details):
        '''
        pretty print episode links from fetch_episode_links
        '''
        info = f"Episode: {self._safe_type_cast(key)}"
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
            if 'filesize' in _vals: info += f' [~{_vals["filesize"]} MB]'

        self._colprint('results', info)

    # step-1
    def search(self, keyword, search_limit=10):
        '''
        search for drama based on a keyword
        '''
        # url encode search keyword
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key
        soup = self._get_bsoup(search_url)

        # get matched items. Limit the search results to be displayed.
        search_titles = [ i.text for i in soup.select(self.search_title_element) ][:search_limit]
        search_links = [ i['href'] for i in soup.select(self.search_link_element) ][:search_limit]

        idx = 1
        search_results = {}
        for title, link in zip(search_titles, search_links):
            if link.startswith('/'):
                link = self.base_url + link
            item = {'title': title, 'link': link}
            # get every search result details
            item.update(self._get_series_info(link))
            item['year'] = item['Release year']
            # add index to every search result
            search_results[idx] = item
            self._show_search_results(idx, item)
            idx += 1

        return search_results

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch episode links as dict containing link, name, upload time
        '''
        all_episodes_list = []
        series_link = target.get('link')
        self.logger.debug(f'Fetching soup to extract episodes from {series_link = }')

        soup = self._get_bsoup(series_link)
        all_episodes_list.extend(self._get_episodes_list(soup))

        while soup.select('.paging'):
            self.logger.debug(f'Found more episodes')
            has_more = re.search("'(.*)','(.*)'", soup.select('.paging')[0]['onclick'])

            if not has_more:
                raise Exception('Show more element not found')
            pg_no, series = has_more.group(1), has_more.group(2)
            more_ep_link = self.episodes_list_url.replace('_series_name_', series).replace('_pg_no_', pg_no)

            self.logger.debug(f'Fetching more episodes for {series = } from {pg_no = }. URL: {more_ep_link}')
            soup = self._get_bsoup(more_ep_link, series_link, {'x-requested-with': 'XMLHttpRequest'})
            all_episodes_list.extend(self._get_episodes_list(soup, True))

        return all_episodes_list[::-1]   # return episodes in ascending

    # step-3
    def show_episode_results(self, items, predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range, threshold=24)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                fmted_name = re.sub(' (\d$)', r' 0\1', item.get('episodeName'))
                self._colprint('results', f"Episode: {fmted_name} | Subs: {item.get('episodeSubs')} | Release date: {item.get('episodeUploadTime')}")

    # step-4
    def fetch_episode_links(self, episodes, ep_start, ep_end):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')

            if float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end:
                self.logger.debug(f'Processing {episode = }')

                self.logger.debug(f'Fetching stream link')
                link = self._get_stream_link(episode.get('episodeLink'), self.stream_links_element)
                self.logger.debug(f'Extracted stream link: {link = }')

                if link is not None:
                    # add episode details & stream link to udb dict
                    self._update_udb_dict(episode.get('episode'), episode)
                    self._update_udb_dict(episode.get('episode'), {'streamLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    gdl_config = {
                        'link': link,
                        'encryption_key': self.__key,
                        'decryption_key': self.__key,
                        'iv': self.__iv,
                        'encrypted_url_args_regex': self.ENCRYPTED_URL_ARGS_REGEX,
                        'download_fetch_link': self.download_fetch_link,
                        'preferred_urls': self.preferred_urls,
                        'blacklist_urls': self.blacklist_urls
                    }
                    m3u8_links = self._get_download_links(**gdl_config)
                    self.logger.debug(f'Extracted {m3u8_links = }')

                    download_links[episode.get('episode')] = m3u8_links
                    self._show_episode_links(episode.get('episode'), m3u8_links)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        drama_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = drama_title if drama_title.endswith(')') else f"{drama_title} ({target_series['Release year']})"

        return target_dir, None

    # step-6
    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        _get_ep_name = lambda resltn: f'{self.udb_episode_dict.get(ep).get("episodeName")} - {resltn}P.mp4'

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
