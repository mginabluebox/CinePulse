from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

def run_spider():
    """
    Run the Metrograph spider and process the scraped data.
    """
    process = CrawlerProcess(get_project_settings())
    process.crawl('metrograph')
    process.start()

if __name__ == "__main__":
    run_spider()