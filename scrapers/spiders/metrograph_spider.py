import scrapy
from datetime import datetime

class MetrographSpider(scrapy.Spider):
    name = 'metrograph'
    start_urls = ['https://metrograph.com/film/']

    def parse(self, response):
        for block in response.css('div.col-sm-12.homepage-in-theater-movie'):
            ### MOVIE-LEVEL INFO
            ## Get movie title
            title = block.css('h3.movie_title a::text').get()
            
            # the last 2 h5s are always director, year / runtime / format
            descript = block.css('h5::text').getall()

            ## Get director(s), save first 2 if there are more than 2
            directors = [x.strip() for x in descript[-2].replace('Director:','').split(',')] 
            director1 = directors[0]
            director2 = None if len(directors) == 1 else directors[1] # only save the first 2 if more than 2 directors
            
            ## Get movie year, runtime, format
            try:
                year, runtime, format = descript[-1].split('/')
                year, runtime, format = year.strip(), runtime.strip(), format.strip()
            except:
                # sometimes format doesn't exist
                year, runtime = descript[-1].split('/')
                year, runtime = year.strip(), runtime.strip()
                format = None
            
            runtime = int(runtime.replace('min','').strip())

            ## Get synopsis
            # todo: get full synopsis
            synopsis = block.css('p.synopsis::text').get()

            ### SHOWTIME-LEVEL INFO
            for st in block.css('div.film_day'):

                ## Get show date and time and format it as a datetime object
                date = st.css('h5.sr-only::text').get() # e.g. Monday January 20
                time = st.css('a::text').get() # e.g. 4:00pm

                date_format = "%B %d %I:%M%p"
                date_string = datetime.strptime(date.split(' ')[1] + ' ' + date.split(' ')[2] + ' ' + time, date_format) # e.g. January 20 4:00pm

                # add year using today's date
                today = datetime.today()
                current_year = today.year

                # check if the show date is in the next year
                if date_string.month < today.month:
                    current_year += 1
                
                timestamp = date_string.replace(year=current_year)
                
                ## Get show day 
                day = date.split(' ')[0] # e.g. Monday

                ## Get ticket link
                ticket_link = 'sold_out'
                if st.css('a').attrib['title'] == 'Buy Tickets':
                    ticket_link = st.css('a').attrib['href']
                
                yield {
                    'title': title,
                    'show_time': timestamp,
                    'show_day': day,
                    'ticket_link': ticket_link,

                    'director1': director1,
                    'director2': director2,
                    'year': year,
                    'runtime': runtime,
                    'format': format,

                    'synopsis': synopsis,
                }