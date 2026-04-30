import os
from playwright.sync_api import sync_playwright

def run_pfg_sourcing():
    with sync_playwright() as p:
        # Launching the browser
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 1. Navigate to PFG Login
        print("Navigating to PFG...")
        page.goto("https://pfgcustomerfirst.com/")
        
        # 2. Login using your System Variables
        # AnythingLLM will pass these from your local machine
        page.fill('input[name="username"]', os.environ.get("PFG_USERNAME", ""))
        page.fill('input[name="password"]', os.environ.get("PFG_PASSWORD", ""))
        page.click('button[type="submit"]')
        
        # 3. Wait for the search bar and search for Chicken
        page.wait_for_selector('input[placeholder*="Search"]')
        page.fill('input[placeholder*="Search"]', 'Chicken Breast')
        page.keyboard.press("Enter")
        
        # 4. Wait for results and save the data
        page.wait_for_load_state("networkidle")
        
        # We save this as a local file that AnythingLLM can then "read" 
        page.pdf(path="pfg_results.pdf")
        print("Sourcing successful. PDF generated.")
        
        browser.close()

if __name__ == "__main__":
    run_pfg_sourcing()
