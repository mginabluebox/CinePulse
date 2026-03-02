import scrapy
from datetime import datetime

class MetrographSpider(scrapy.Spider):
    name = 'metrograph'
    start_urls = ['https://metrograph.com/film/']

    def parse(self, response):
        for block in response.css('div.col-sm-12.homepage-in-theater-movie'):
            ### MOVIE-LEVEL INFO
            ## Get movie title
            title = block.css('h3.movie_title a::text').get(default="").strip()

            # Poster image used on the listing
            image_url = block.css('img::attr(src)').get()
            
            # the last 2 h5s are always director, year / runtime / format
            descript = block.css('h5::text').getall()

            ## Get director(s), save first 2 if there are more than 2
            try:
                directors = [x.strip() for x in descript[-2].replace('Director:','').split(',')] 
                director1 = directors[0]
                director2 = None if len(directors) == 1 else directors[1] # only save the first 2 if more than 2 directors
            except:
                director1 = None
                director2 = None

            ## Get movie year, runtime, format
            try:
                year, runtime, format = descript[-1].split('/')
                year, runtime, format = year.strip(), runtime.strip(), format.strip()
            except:
                # sometimes format doesn't exist
                year, runtime = descript[-1].split('/')
                year, runtime = year.strip(), runtime.strip()
                format = 'UNKNOWN'
            
            runtime = int(runtime.replace('min','').strip())

            ## Get synopsis
            # todo: get full synopsis
            synopsis = block.css('p.synopsis::text').get()

            ### SHOWTIME-LEVEL INFO
            showtimes = block.css('div.showtimes')
            # accept either <h5 class="sr-only"> or plain <h6> headings
            headings = showtimes.css('h5.sr-only, h6')
            days = showtimes.css('div.film_day')
            for heading, day_div in zip(headings, days):
                # heading example: <h5 class="sr-only">Sun Dec <span class="day-number">14</span></h5>
                date_text = heading.xpath('normalize-space(text())').get()  # e.g. "Sun Dec"
                day_number = heading.css('span.day-number::text').get()    # e.g. "14"
                time_el = day_div.css('a')
                time_text = time_el.xpath('normalize-space(text())').get()  # e.g. "4:40pm" or "Sold Out"
                
                # Defensive checks
                if not time_text:
                    self.logger.warning(f"Skipping showtime (no time) for title={title!r} date={date_text!r} day_number={day_number!r}")
                    continue
                time_text = time_text.strip()
                
                # build candidate date strings (preserve your existing parsing logic below)
                candidates = []
                if date_text:
                    # date_text like "Sun Dec" -> month part is second token
                    parts = date_text.split()
                    month_part = parts[1] if len(parts) > 1 else parts[0]
                    if day_number:
                        candidates.append(f"{month_part} {day_number} {time_text}")
                        candidates.append(f"{parts[0]} {month_part} {day_number} {time_text}")
                    else:
                        candidates.append(f"{date_text} {time_text}")

                # possible datetime formats to try
                date_formats = [
                    "%b %d %I:%M%p",   # e.g. Dec 14 4:00PM (abbr month)
                    "%B %d %I:%M%p",   # e.g. December 14 4:00PM (full month)
                    "%a %b %d %I:%M%p",# e.g. Sun Dec 14 4:00PM
                    "%A %B %d %I:%M%p",# e.g. Sunday December 14 4:00PM
                    "%b %d %I:%M %p",
                    "%B %d %I:%M %p",
                    "%a %b %d %I:%M %p",
                    "%A %B %d %I:%M %p",
                ]

                parsed_dt = None
                for cand in candidates:
                    for fmt in date_formats:
                        try:
                            parsed_dt = datetime.strptime(cand, fmt)
                            break
                        except Exception:
                            continue
                    if parsed_dt:
                        break

                if not parsed_dt:
                    # final fallback: try to extract numeric day with regex and month name/abbr
                    self.logger.error(f"Failed to parse date/time for title={title!r}: date_text={date_text!r} day_number={day_number!r} time={time_text!r}")
                    continue

                # add year using today's date
                today = datetime.today()
                current_year = today.year
                # if the parsed month is earlier in the year than now, assume it's next year
                if parsed_dt.month < today.month:
                    current_year += 1

                timestamp = parsed_dt.replace(year=current_year)

                # derive show day name from the final timestamp (after year is applied)
                try:
                    show_day = timestamp.strftime('%A')
                except Exception:
                    show_day = None
 

                ## Get ticket link safely
                ticket_link = 'sold_out'
                title_attr = day_div.css('a::attr(title)').get()
                href_attr = day_div.css('a::attr(href)').get()
                if title_attr and 'Buy Tickets' in title_attr and href_attr:
                    ticket_link = href_attr

                yield {
                    'title': title,
                    'show_time': timestamp,
                    'show_day': show_day,
                    'ticket_link': ticket_link,

                    'image_url': image_url,

                    'director1': director1,
                    'director2': director2,
                    'year': year,
                    'runtime': runtime,
                    'format': format,

                    'synopsis': synopsis,
                }