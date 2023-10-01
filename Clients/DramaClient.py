__author__ = 'Prudhvi PLN'

import json
import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class DramaClient(BaseClient):
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
        self.m3u8_fetch_link = config['m3u8_fetch_link']
        self.preferred_urls = config['preferred_urls']
        self.blacklist_urls = config['blacklist_urls']
        # key & iv for decryption & encrytion. Don't know why it is working only for these
        # Reference: https://github.com/CoolnsX/dra-cla/blob/main/dra-cla
        self.key = '3933343232313932343333393532343839373532333432393038353835373532'
        self.iv = '39323632383539323332343335383235'
        self.logger.debug(f'Drama client initialized with {config = }')

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

        return meta

    def _get_stream_link(self, link):
        '''
        return stream link of asianhd
        '''
        self.logger.debug(f'Extract stream link from soup for {link = }')
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        for stream in soup.select(self.stream_links_element):
            if 'streaming.php' in stream['data-video']:
                stream_link = stream['data-video']
                if stream_link.startswith('/'):
                    stream_link = 'https:' + stream_link
                return stream_link

    def _show_search_results(self, key, details):
        '''
        pretty print drama results based on your search
        '''
        line = f"{key}: {details.get('title')} | Country: {details.get('Country')}\n   " + \
                f"| Released: {details.get('year')} | Status: {details.get('Status')} " + \
                f"| Genre: {details.get('Genre')}"
        print(line)

    def _show_episode_links(self, key, details):
        '''
        pretty print episode links from fetch_episode_links
        '''
        info = f"Episode: {self._safe_type_cast(key)}"
        for _res in details:
            if 'errorMsg' in _res:
                info += f' | {_res["errorMsg"]}'
                self.logger.warning(info)
            else:
                _reskey = next(iter(_res))
                info += f' | {_reskey}P ({_res[_reskey]["resolution_size"]})' #| URL: {_res[_reskey]["m3u8Link"]}
        print(info)

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

    def _parse_m3u8_links(self, master_m3u8_link, referer):
        '''
        parse master m3u8 data and return dict of resolutions and m3u8 links
        '''
        m3u8_links = []
        base_url = '/'.join(master_m3u8_link.split('/')[:-1])
        self.logger.debug(f'Extracting m3u8 data from master link: {master_m3u8_link}')
        master_m3u8_data = self._send_request(master_m3u8_link, referer, False)
        # self.logger.debug(f'{master_m3u8_data = }')

        _regex_list = lambda data, rgx, grp: [ url.group(grp) for url in re.finditer(rgx, data) ]
        resolutions = _regex_list(master_m3u8_data, 'RESOLUTION=(.*),', 1)
        resolution_names = _regex_list(master_m3u8_data, 'NAME="(.*)"', 1)
        resolution_links = _regex_list(master_m3u8_data, '(.*)m3u8', 0)

        # if master m3u8 does not contain any resolutions, use default
        if len(resolution_links) == 0:
            m3u8_links.append({'original': {'resolution_size': 'original', 'm3u8Link': master_m3u8_link}})
            return m3u8_links

        for _res, _pixels, _link in zip(resolution_names, resolutions, resolution_links):
            # prepend base url if it is relative url
            m3u8_link = _link if _link.startswith('http') else base_url + '/' + _link
            m3u8_links.append({
                _res.replace('p',''): {
                    'resolution_size': _pixels,
                    'm3u8Link': m3u8_link
                }
            })

        return m3u8_links

    def _get_m3u8_links(self, link):
        '''
        retrieve m3u8 links from stream link and return available resolution links
        '''
        # extract url params & get id value
        uid = { i.split('=')[0]:i.split('=')[1] for i in link.split('?')[1].split('&') }.get('id')
        self.logger.debug(f'Extracted {uid = }')
        if uid is None or uid == '':
            return [{'errorMsg': 'id not found in Stream link'}]

        # encrypt the uid with new cipher
        self.logger.debug(f'Creating encrypted link')
        cipher = self._get_cipher(self.key, self.iv)
        encrypted_id = self._encrypt(uid, cipher)
        stream_base_url = '/'.join(link.split('/')[:3])
        encrypted_link = f'{stream_base_url}/{self.m3u8_fetch_link}{encrypted_id}'
        self.logger.debug(f'{encrypted_link = }')

        # get encrpyted response with m3u8 links
        self.logger.debug(f'Fetch m3u8 links from encrypted url')
        response = self._send_request(encrypted_link, link, False)

        try:
            encrypted_m3u8_response = json.loads(response)['data']
            self.logger.debug(f'{encrypted_m3u8_response = }')

            # decode m3u8 response with new cipher
            self.logger.debug(f'Decoding m3u8 response')
            cipher = self._get_cipher(self.key, self.iv)
            decoded_m3u8_response = self._decrypt(encrypted_m3u8_response, cipher)
            self.logger.debug(f'{decoded_m3u8_response = }')
            master_m3u8_links = json.loads(decoded_m3u8_response)

        except Exception as e:
            return [{'errorMsg': f'Invalid response received. Error: {e}'}]

        # get m3u8 links containing resolutions [ source, bkp_source ]
        master_m3u8_links = [ master_m3u8_links.get('source')[0]['file'], master_m3u8_links.get('source_bk')[0]['file'] ]
        self.logger.debug(f'[source, bkp_source]: {master_m3u8_links = }')

        # re-order urls based on user preference
        ordered_master_m3u8_links = [ j for i in self.preferred_urls for j in master_m3u8_links if i in j ]
        # append remaining urls
        ordered_master_m3u8_links.extend([ j for j in master_m3u8_links if j not in ordered_master_m3u8_links ])
        # remove blacklisted urls
        ordered_master_m3u8_links = [ j for j in ordered_master_m3u8_links if not any(i in j for i in self.blacklist_urls) ]
        self.logger.debug(f'{ordered_master_m3u8_links = }')

        m3u8_links = []
        for master_m3u8_link in ordered_master_m3u8_links:
            try:
                self.logger.debug(f'Getting m3u8 from: {master_m3u8_link = }')
                m3u8_links = self._parse_m3u8_links(master_m3u8_link, link)
                self.logger.debug(f'Returned {m3u8_links = }')
                if len(m3u8_links) > 0:
                    self.logger.debug('m3u8 links obtained. No need to try with alternative. Breaking loop')
                    break
            except Exception as e:
                self.logger.warning(f'Failed to fetch m3u8 links from {master_m3u8_link = }. Trying with alternative...')
                pass    # pass to alternate source

        return m3u8_links

    def search(self, keyword):
        '''
        search for drama based on a keyword
        '''
        # mask search keyword
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key
        soup = self._get_bsoup(search_url)

        # get matched items
        search_titles = [ i.text for i in soup.select(self.search_title_element) ]
        search_links = [ i['href'] for i in soup.select(self.search_link_element) ]

        idx = 1
        search_results = {}
        for title, link in zip(search_titles, search_links):
            if link.startswith('/'):
                link = self.base_url + link
            item = {'title': title, 'link': link}
            item.update(self._get_series_info(link))
            item['year'] = item['Release year']
            # add index to every search result
            search_results[idx] = item
            self._show_search_results(idx, item)
            idx += 1

        return search_results

    def show_search_results(self, items):
        '''
        print all drama results based on your search at once if required
        '''
        for idx, item in items.items():
            self._show_search_results(idx, item)

    def fetch_episodes_list(self, target):
        '''
        fetch episode links as dict containing link, name, upload time
        '''
        all_episode_list = []
        series_link = target.get('link')
        self.logger.debug(f'Fetching soup to extract episodes from {series_link = }')

        soup = self._get_bsoup(series_link)
        all_episode_list.extend(self._get_episodes_list(soup))

        while soup.select('.paging'):
            self.logger.debug(f'Found more episodes')
            has_more = re.search("'(.*)','(.*)'", soup.select('.paging')[0]['onclick'])

            if not has_more:
                raise Exception('Show more element not found')
            pg_no, series = has_more.group(1), has_more.group(2)
            more_ep_link = self.episodes_list_url.replace('_series_name_', series).replace('_pg_no_', pg_no)

            self.logger.debug(f'Fetching more episodes for {series = } from {pg_no = }. URL: {more_ep_link}')
            soup = self._get_bsoup(more_ep_link, series_link, {'x-requested-with': 'XMLHttpRequest'})
            all_episode_list.extend(self._get_episodes_list(soup, True))

        return all_episode_list[::-1]   # return episodes in ascending

    def show_episode_results(self, items):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        cnt = show = len(items)
        if cnt > 24:
            show = int(input(f'Total {cnt} episodes found. Enter range to display [default=ALL]: ') or cnt)
            print(f'Showing top {show} episodes:')
        for item in items[:show]:
            fmted_name = re.sub(' (\d$)', r' 0\1', item.get('episodeName'))
            print(f"Episode: {fmted_name} | Subs: {item.get('episodeSubs')} | Release date: {item.get('episodeUploadTime')}")

    def fetch_episode_links(self, episodes, ep_start, ep_end):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        for episode in episodes:
            self.logger.debug(f'Current {episode = }')

            if float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end:
                self.logger.debug(f'Is selected')

                self.logger.debug(f'Fetching stream link')
                link = self._get_stream_link(episode.get('episodeLink'))
                self.logger.debug(f'Extracted stream link: {link = }')

                if link is not None:
                    # add episode details & stream link to udb dict
                    self._update_udb_dict(episode.get('episode'), episode)
                    self._update_udb_dict(episode.get('episode'), {'streamLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    m3u8_links = self._get_m3u8_links(link)
                    self.logger.debug(f'Extracted {m3u8_links = }')

                    download_links[episode.get('episode')] = m3u8_links
                    self._show_episode_links(episode.get('episode'), m3u8_links)

        return download_links

    def show_episode_links(self, items):
        '''
        print all episodes details at once if required
        '''
        for item, details in items.items():
            self._show_episode_links(item, details)

    def set_out_names(self, target_series):
        drama_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = drama_title if drama_title.endswith(')') else f"{drama_title} ({target_series['Release year']})"

        return target_dir, None

    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        has_key = lambda x, y: y in x.keys()

        for ep, link in target_links.items():
            self.logger.debug(f'Epsiode: {ep}, Link: {link}')
            info = f'Episode: {self._safe_type_cast(ep)} |'
            res_dict = [ i.get(resolution) for i in link if has_key(i, resolution) ]
            if len(res_dict) == 0:
                self.logger.error(f'{info} Resolution [{resolution}] not found')
            else:
                try:
                    ep_name = f'{self.udb_episode_dict.get(ep).get("episodeName")} - {resolution}P.mp4'
                    ep_link = res_dict[0]['m3u8Link']
                    # add m3u8 against episode
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'm3u8Link': ep_link})
                    self.logger.debug(f'{info} Link found [{ep_link}]')
                    print(f'{info} Link found [{ep_link}]')
                except Exception as e:
                    self.logger.error(f'{info} Failed to fetch link with error [{e}]')

        final_dict = { k:v for k,v in self._get_udb_dict().items() if v.get('m3u8Link') is not None }

        return final_dict
