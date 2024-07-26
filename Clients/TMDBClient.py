import requests
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


BASE_URL = 'https://www.themoviedb.org/'
class TMDBClient(BaseClient):
    '''
    Client to search and return TMDB ID for movies/series.
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', BASE_URL)
        self.search_url = self.base_url + config.get('search_url', 'search?query=')
        self.search_link_element = config.get('search_link_element', '.details a.result')
        self.series_info_element = config.get('series_info_element', 'section.facts p')
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'TMDB client initialized with {config = }')

    @staticmethod
    def is_reachable() -> bool:
        '''Check if TMDB is reachable'''
        try:
            requests.get(BASE_URL, timeout=5)
            return True
        except:
            return False

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of movie/show
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        if soup is None:
            return meta

        meta['type'] = link.split('/')[-2].lower()

        for i in soup.select(self.series_info_element):
            k = i.get_text(':', strip=True)
            meta[k.split(':')[0]] = k.split(':')[-1]

        # add additional metadata. Metadata extraction elements are hardcoded. This may change depending on TMDB website.
        try:
            meta['genre'] = ', '.join([ i.text.strip() for i in soup.select('span.genres a') ])
            meta['score'] = soup.select_one('div.user_score_chart').get('data-percent')
            meta['year'] = soup.select_one('span.release_date').text.strip().replace('(', '').replace(')', '')
            meta['runtime'] = soup.select_one('span.runtime').text.strip()
        except:
            pass

        # add count of seasons & episodes if it is a released series
        if meta['type'] == 'tv' and meta.get('year') is not None:
            try:
                # this is an extra api call just to fetch season and episode counts
                self.logger.debug('Fetching season and episode counts...')
                seasons_soup = self._get_bsoup(link.replace('?', '/seasons?'), silent=True)
                season_ep_cnts = {}
                for ele in seasons_soup.select('div.season_wrapper'):
                    s = ele.select_one('h2').text
                    e = ele.select_one('h4').get_text(':', strip=True).split()[-2]
                    season_ep_cnts[s] = e

                self.logger.debug(f'Episodes count per season: {season_ep_cnts}')
                # filter out special / extra seasons
                s_cnt = sum('season' in k.lower() for k in season_ep_cnts.keys())
                e_cnt = sum(int(v) for k,v in season_ep_cnts.items() if 'season' in k.lower())
                if s_cnt != 0 or e_cnt != 0:
                    meta['seasons'], meta['episodes'], meta['episodes_per_season'] = s_cnt, e_cnt, season_ep_cnts

            except:
                pass

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print the results based on your search
        '''
        line = f"{key}: {details.get('title')} | Language: {details.get('Original Language', 'N/A')} | Genre: {details.get('genre', 'N/A')}" + \
                f"\n   | Type: {'TV Show' if details.get('type') == 'tv' else details.get('type').capitalize()} | User Score: {details.get('score', '0')}% " + \
                f"| Released: {details.get('year', 'N/A')} | Status: {details.get('Status')}"

        if details.get('type').lower() == 'movie':
            line += f"\n   | Duration: {details.get('runtime', 'N/A')}"
        else:
            line += f"\n   | Seasons: {details.get('seasons', 'N/A')} | Total Episodes: {details.get('episodes', 'N/A')}"

        self._colprint('results', line)

    # step-1
    def search(self, keyword, search_limit=5):
        '''
        search for movie/show based on a keyword using TMDB API.
        '''
        valid_types = ['movie', 'tv']
        # url encode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key + '&language=en-US'
        soup = self._get_bsoup(search_url)

        # get matched items. Limit the search results to be displayed.
        search_links = [ i for i in soup.select(self.search_link_element) if i['data-media-type'].lower() in valid_types ][:search_limit]

        idx = 1
        search_results = {}
        for element in search_links:
            title, link = element.text, element['href']
            if link.startswith('/'):
                link = self.base_url + link

            # Add mandatory information
            tmdb_id = link.split('?')[0].split('/')[-1].split('-')[0]
            item = {
                'title': title, 'link': link,
                'show_id': tmdb_id, 'year': 'XXXX'
            }

            data = self._get_series_info(link)
            if data:
                # Add additional information
                item.update(data)
                # Add index to every search result
                search_results[idx] = item
                self._show_search_results(idx, item)
                idx += 1

        return search_results
