import scrapy


class MetrographSpider(scrapy.Spider):
    name = 'metrograph'
    start_urls = ['https://metrograph.com/film/']

    def parse(self, response):
        for block in response.css('div.col-sm-12.homepage-in-theater-movie'):

            title = block.css('h3.movie_title a::text').get()
            
            # the last 2 h5s are always director, year / runtime / format
            descript = block.css('h5::text').getall()

            directors = [x.strip() for x in descript[-2].replace('Director:','').split(',')] 
            director1 = directors[0]
            director2 = None if len(directors) == 1 else directors[1] # only save the first 2 if more than 2 directors
            
            try:
                year, runtime, format = descript[-1].split('/')
                year, runtime, format = year.strip(), runtime.strip(), format.strip()
            except:
                # sometimes format doesn't exist
                year, runtime = descript[-1].split('/')
                year, runtime = year.strip(), runtime.strip()
                format = None
            
            # todo: get full synopsis
            synopsis = block.css('p.synopsis::text').get()

            for st in block.css('div.film_day'):
                
                date = st.css('h5.sr-only::text').get() # e.g. Monday January 20
                date = date.split(' ')[1] + date.split(' ')[2]
                time = st.css('a::text').get() # e.g. 4:00pm

                ticket_link = 'sold_out'
                if st.css('a').attrib['title'] == 'Buy Tickets':
                    ticket_link = st.css('a').attrib['href']
                
                yield {
                    'title': title,
                    'show_date': date,
                    'show_time': time,
                    'ticket_link': ticket_link,

                    'director1': director1,
                    'director2': director2,
                    'year': year,
                    'runtime': runtime,
                    'format': format,

                    'synopsis': synopsis,
                }