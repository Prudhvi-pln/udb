from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class IMDBClient(BaseClient):
    '''
    Client to search and return IMDB ID for movies/series.
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://www.imdb.com/')
        self.search_url = self.base_url + config.get('search_url', 'find/?q=')
        self.season_url = config.get('season_url', 'episodes/?season=')
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'TMDB client initialized with {config = }')

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

        # add additional metadata. Metadata extraction elements are hardcoded. This may change depending on IMDB website.
        is_series = soup.select_one('div a span.episode-guide-text')
        series_type = 'tv' if is_series else 'movie'
        meta = {'type': series_type}

        year, pg, duration = None, None, None
        for elem in soup.select('section div ul li'):
            ele = elem.select_one('a')
            if ele is None:
                txt = elem.get_text(' ', strip=True).lower()
                if 'runtime' in txt:
                    duration = txt.replace('runtime', '').strip()
                continue
            if year is None and '/releaseinfo' in ele['href']:
                year = ele.text.strip().replace('–', '-')
                if not year[:4].isdigit(): year = None
            elif pg is None and '/parentalguide' in ele['href']:
                pg = ele.text.strip()

        if year: meta['year'] = year
        if pg: meta['pg_rating'] = pg
        if duration: meta['runtime'] = duration

        try:
            meta['genre'] = ', '.join([ i.text for i in soup.select('div.ipc-chip-list__scroller a') ])
            meta['rating'] = soup.select('div.rating-bar__base-button')[0].get_text('|').split('|')[1]
        except:
            pass

        # add count of seasons & episodes
        if series_type == 'tv':
            try:
                season_ep_cnts = {}
                seasons = [ i['value'] for i in soup.select('#browse-episodes-season option') if i.get('value') ][-2::-1]
                if len(seasons) == 0: seasons = ['1']       # if there is only one season, then above won't work, so add default 1 season
                for season in seasons:
                    season_url = link.split('?')[0] + self.season_url + str(season)
                    self.logger.debug(f'Fetching season and episode counts from [{season_url}]...')
                    seasons_soup = self._get_bsoup(season_url, extra_headers={'Accept-Language': 'en-US,en'}, silent=True)
                    ep_cnt = len(seasons_soup.select('section a div.ipc-title__text')) if seasons_soup else 0
                    season_ep_cnts[season] = ep_cnt
                    self.logger.debug(f'Episode count for season-{season}: {ep_cnt}')

                self.logger.debug(f'Episodes count per season: {season_ep_cnts}')
                s_cnt = len(season_ep_cnts.keys())
                e_cnt = sum(int(v) for v in season_ep_cnts.values())
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
        line = f"{key}: {details.get('title')} | PG Rating: {details.get('pg_rating', 'NA')} | Genre: {details.get('genre', 'N/A')}" + \
                f"\n   | Type: {'TV Show' if details.get('type') == 'tv' else details.get('type').capitalize()} | IMDB Rating: {details.get('rating', 'N/A')} " +\
                f"| Released: {details.get('year', 'N/A')}"

        if details.get('type').lower() == 'tv':
            line += f"\n   | Seasons: {details.get('seasons', 'N/A')} | Total Episodes: {details.get('episodes', 'N/A')} | Duration: {details.get('runtime', 'N/A')}"
        else:
            line += f"\n   | Duration: {details.get('runtime', 'N/A')}"

        self._colprint('results', line)

    # step-1
    def search(self, keyword, search_limit=5):
        '''
        search for movie/show based on a keyword using TMDB API.
        '''
        # url encode the search word
        search_url = self.search_url + quote_plus(keyword)
        soup = self._get_bsoup(search_url, extra_headers={'Accept-Language': 'en-US,en'})

        # Parse the title, link attributes
        links = [ i for i in soup.select('ul li a') if 'title/' in i['href'] ][:search_limit]

        idx = 1
        search_results = {}
        for i in links:
            title, link = i.text, i['href']
            imdb_id = link.split('/')[2]        # get imdb id
            if link.startswith('/'):
                link = self.base_url + link

            # Add mandatory information
            item = {'title': title, 'link': link, 'show_id': imdb_id}

            data = self._get_series_info(link)
            if data:
                # Add additional information
                item.update(data)
                # Add index to every search result
                search_results[idx] = item
                self._show_search_results(idx, item)
                idx += 1

        return search_results
