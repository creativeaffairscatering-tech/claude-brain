from playwright.sync_api import sync_playwright
import os

def run_sourcing():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Performance Foodservice Login
        page.goto("https://pfgcustomerfirst.com")
        page.fill('input[type="email"]', os.getenv("PFG_USERNAME"))
        page.fill('input[type="password"]', os.getenv("PFG_PASSWORD"))
        page.click('button[type="submit"]')
        
        # Wait for the dashboard to load, then search
        page.wait_for_selector('input[placeholder*="Search"]')
        page.fill('input[placeholder*="Search"]', 'Chicken Breast')
        page.keyboard.press("Enter")
        
        # Capture the results
        page.wait_for_load_state("networkidle")
        page.screenshot(path="prices.png") 
        print("Sourcing Complete. Data saved to prices.png")
        browser.close()

run_sourcing()
