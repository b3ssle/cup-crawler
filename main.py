import logging
from flask import Flask
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import os
from pymongo import MongoClient
import re
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

client = MongoClient(os.getenv('MONGODB_URI'))
db = client['matches_db']
collection = db['empress_matches']

class EmpressCupCrawler:
    def __init__(self):
        self.schedule_url = "https://www.jfa.jp/match/empressscup_2024/schedule_result/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        self.rounds = {
            "3": {"last_match": "M028", "date": "2024-12-01"},
            "4": {"last_match": "M032", "date": "2024-12-08"},
            "5": {"last_match": "M040", "date": "2024-12-15"},
            "準々決勝": {"last_match": "M044", "date": "2024-12-22"},
            "準決勝": {"last_match": "M046", "date": "2025-01-18"},
            "決勝": {"last_match": "M047", "date": "2025-01-25"}
        }
    
    def parse_match_info(self, text: str) -> Dict:
        logger.info("開始解析比賽資訊")
        soup = BeautifulSoup(text, 'html.parser')
        
        match_id = None
        for line in text.split('\n'):
            if 'M0' in line:
                match_id = re.search(r'M0\d+', line)
                if match_id:
                    match_id = match_id.group()
                    logger.info(f"找到比賽ID: {match_id}")
                    break
        
        if not match_id:
            logger.warning("未找到比賽ID")
            return {}
            
        match_info = {
            'id': match_id,
            'status': 'scheduled'
        }
        
        score_text = soup.find('td', class_='score')
        if score_text:
            score = score_text.text.strip()
            if score and score != '―':
                match_info['score'] = score
                match_info['status'] = 'completed'
                logger.info(f"比賽 {match_id} 已完成，比分: {score}")
                
        teams = soup.find_all('td', class_='team')
        if len(teams) >= 2:
            match_info['home_team'] = teams[0].text.strip()
            match_info['away_team'] = teams[1].text.strip()
            logger.info(f"比賽隊伍: {match_info['home_team']} vs {match_info['away_team']}")
            
        date_venue = soup.find('td', class_='date')
        if date_venue:
            date_text = date_venue.text.strip()
            if date_text:
                match_info['date'] = date_text
                logger.info(f"比賽日期: {date_text}")
                
        return match_info

    def extract_match_blocks(self, html_content: str) -> List[str]:
        logger.info("開始提取比賽區塊")
        soup = BeautifulSoup(html_content, 'html.parser')
        matches = []
        
        match_rows = soup.find_all('tr', class_='match')
        logger.info(f"找到 {len(match_rows)} 個比賽區塊")
        for row in match_rows:
            matches.append(str(row))
            
        return matches

    def update_matches(self) -> Dict:
        try:
            logger.info("開始爬取網頁...")
            response = requests.get(self.schedule_url, headers=self.headers)
            response.raise_for_status()
            response.encoding = 'utf-8'
            logger.info(f"網頁回應狀態: {response.status_code}")
            
            match_blocks = self.extract_match_blocks(response.text)
            logger.info(f"找到 {len(match_blocks)} 場比賽")
            
            updated_data = {}
            for block in match_blocks:
                match_info = self.parse_match_info(block)
                if match_info:
                    updated_data[match_info['id']] = match_info
            
            logger.info(f"成功解析 {len(updated_data)} 場比賽資料")
            return updated_data
            
        except Exception as e:
            logger.error(f"更新比賽時發生錯誤: {str(e)}")
            return {}

@app.route('/crawl', methods=['POST'])
def handle_crawl():
    try:
        logger.info("開始爬蟲程序")
        crawler = EmpressCupCrawler()
        matches = crawler.update_matches()
        
        logger.info(f"找到 {len(matches)} 場比賽")
        
        if matches:
            for match_id, match_data in matches.items():
                logger.info(f"更新比賽 {match_id}")
                collection.update_one(
                    {'match_id': match_id},
                    {'$set': {
                        **match_data,
                        'updated_at': datetime.now()
                    }},
                    upsert=True
                )
            
            return {
                "status": "success",
                "matches_updated": len(matches),
                "timestamp": datetime.now().isoformat()
            }, 200
        
        logger.info("沒有新的更新")
        return {"status": "no_updates"}, 200
        
    except Exception as e:
        logger.error(f"錯誤: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))