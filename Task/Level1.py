import requests
import json
import anthropic
import time
import random
import re
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

class BrowserAutomation:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.browser = None
        self.last_result = None
        self.setup_browser()

    def setup_browser(self):
        """Initialize the browser with Selenium"""
        try:
            chrome_options = Options()
            chrome_options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-notifications")
            chrome_options.add_argument("--ignore-certificate-errors")
            service = Service(ChromeDriverManager().install())
            self.browser = webdriver.Chrome(service=service, options=chrome_options)
            self.browser.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            logging.info("Browser initialized successfully")
        except Exception as e:
            logging.error(f"Error setting up browser: {str(e)}")
            raise

    def random_sleep(self, min_seconds=1, max_seconds=3):
        """Sleep for a random amount of time to mimic human behavior"""
        import time
        if not hasattr(time, 'sleep'):
            logging.error("time module is corrupted")
            raise ImportError("time module is not properly imported")
        time.sleep(random.uniform(min_seconds, max_seconds))

    def wait_for_page_load(self, timeout=30):
        """Wait for page to fully load, including dynamic content"""
        try:
            WebDriverWait(self.browser, timeout).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            WebDriverWait(self.browser, timeout).until(
                lambda driver: driver.execute_script("return window.performance.timing.loadEventEnd > 0")
            )
            self.random_sleep(2, 5)
        except Exception as e:
            logging.warning(f"Wait for page load issue: {str(e)}")

    def handle_popups(self):
        """Handle popups/overlays across various websites"""
        try:
            popup_selectors = [
                "button.close", ".close", "button[class*='close']",
                ".modal-close", "button[aria-label*='close']",
                "//button[contains(text(), 'Close')]", "//button[contains(text(), 'X')]",
                "//button[contains(text(), 'No thanks')]", "//button[contains(text(), 'Not now')]",
                "button.accept", "//button[contains(text(), 'Accept')]",
                "div._2QfC02 button"  # Flipkart login popup
            ]
            for selector in popup_selectors:
                try:
                    if selector.startswith('//'):
                        elements = self.browser.find_elements(By.XPATH, selector)
                    else:
                        elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        elements[0].click()
                        logging.info(f"Closed popup using selector: {selector}")
                        self.random_sleep(1, 2)
                except Exception:
                    continue
        except Exception as e:
            logging.warning(f"Error handling popups: {str(e)}")

    def scroll_page(self, scroll_pause_time=2):
        """Scroll page to load lazy-loaded content"""
        try:
            last_height = self.browser.execute_script("return document.body.scrollHeight")
            self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            self.random_sleep(scroll_pause_time, scroll_pause_time + 2)
        except Exception as e:
            logging.warning(f"Error during page scrolling: {str(e)}")

    def extract_data(self, url, extraction_rules):
        """Extract structured data from any webpage, supporting multiple selectors"""
        logging.info(f"Navigating to {url}")
        try:
            self.browser.get(url)
            self.wait_for_page_load()
            self.handle_popups()
            self.scroll_page()
            wait = WebDriverWait(self.browser, 20)
            extracted_data = {}
            for field_name, selectors in extraction_rules.items():
                logging.info(f"Extracting '{field_name}'")
                if isinstance(selectors, str):
                    selector_list = [selectors]
                elif isinstance(selectors, list):
                    selector_list = selectors
                else:
                    extracted_data[field_name] = f"Invalid selector format for {field_name}"
                    logging.error(f"Invalid selector format for {field_name}")
                    continue
                for selector in selector_list:
                    logging.info(f"Trying selector '{selector}' for '{field_name}'")
                    try:
                        for attempt in range(3):
                            try:
                                if selector.startswith('/'):
                                    element = wait.until(
                                        EC.visibility_of_element_located((By.XPATH, selector))
                                    )
                                else:
                                    element = wait.until(
                                        EC.visibility_of_element_located((By.CSS_SELECTOR, selector))
                                    )
                                extracted_data[field_name] = element.text.strip()
                                logging.info(f"Successfully extracted '{field_name}': {extracted_data[field_name]}")
                                break
                            except (StaleElementReferenceException, TimeoutException) as e:
                                if attempt < 2:
                                    logging.info(f"Retry attempt {attempt + 1} for '{field_name}' with '{selector}'")
                                    self.random_sleep(1, 2)
                                else:
                                    raise e
                        if field_name in extracted_data:
                            break
                    except Exception as e:
                        logging.warning(f"Selector '{selector}' failed for '{field_name}': {str(e)}")
                if field_name not in extracted_data:
                    extracted_data[field_name] = self.try_adaptive_extraction(field_name)
                    if extracted_data[field_name]:
                        logging.info(f"Adaptive extraction succeeded for '{field_name}': {extracted_data[field_name]}")
                    else:
                        extracted_data[field_name] = f"Could not extract {field_name}"
                        logging.warning(f"Failed to extract '{field_name}' after all attempts")
            if all("Could not extract" in str(v) for v in extracted_data.values()):
                extracted_data["page_source_sample"] = self.browser.page_source[:1000] + "..."
            return extracted_data
        except Exception as e:
            logging.error(f"Failed to load page or extract data: {str(e)}")
            return {"error": f"Failed to extract data: {str(e)}"}

    def try_adaptive_extraction(self, field_name):
        """Adaptive extraction for any page based on field name"""
        try:
            field_lower = field_name.lower()
            if "rating" in field_lower or "stars" in field_lower:
                selectors = [
                    ".rating", "div[class*='rating']", "span[class*='stars']",
                    ".stars", "div[class*='stars']", "span[class*='rating']",
                    ".average-rating", "span[class*='average']",
                    "//span[contains(text(), 'out of')]", "//div[contains(text(), '/5')]",
                    "div._3LWZlK", "span.rating-value",
                    ".a-icon-star", ".review-rating"
                ]
                for selector in selectors:
                    try:
                        if selector.startswith('//'):
                            elements = self.browser.find_elements(By.XPATH, selector)
                        else:
                            elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            text = elements[0].text.strip()
                            if text and re.search(r'\d+(\.\d+)?', text):
                                return text
                    except Exception:
                        continue
                page_text = self.browser.find_element(By.TAG_NAME, "body").text
                rating_patterns = [
                    r'(\d+\.\d+|\d+) out of 5', r'(\d+\.\d+|\d+)/5',
                    r'(\d+\.\d+|\d+) stars', r'Rating: (\d+\.\d+|\d+)'
                ]
                for pattern in rating_patterns:
                    match = re.search(pattern, page_text)
                    if match:
                        return match.group(1)
            return None
        except Exception as e:
            logging.error(f"Error in adaptive extraction for {field_name}: {str(e)}")
            return None

    def get_extraction_rules_from_claude(self, url, user_request):
        """Generate extraction rules using Claude with single-string selectors"""
        try:
            self.browser.get(url)
            self.wait_for_page_load()
            page_title = self.browser.title
            prompt = f"""
            Given the URL '{url}' with page title '{page_title}' and the user request '{user_request}', generate a Python dictionary of extraction rules for Selenium to extract structured data from the webpage. The dictionary should map field names (as strings) to a SINGLE CSS selector or XPath expression (as a string) that targets the requested data. Do NOT return lists of selectors—provide only one selector per field.
            Use these common selector patterns:
            - Ratings: '.rating', 'div[class*=\"rating\"]', 'span[class*=\"stars\"]', '.average-rating', '//span[contains(text(), \"out of 5\")]'
            - Review counts: '.reviews', 'span[class*=\"review\"]', '.review-count', '//span[contains(text(), \"reviews\")]'
            - Product names: 'h1', '.product-name', '.product-title'
            - Prices: '.price', 'span.price', 'div[class*=\"price\"]'
            Return ONLY the raw Python dictionary as plain text, with proper syntax.
            """
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                temperature=0,
                system="You are an expert in web scraping and Selenium.",
                messages=[{"role": "user", "content": prompt}]
            )
            return eval(message.content[0].text)
        except Exception as e:
            logging.error(f"Error generating rules from Claude: {str(e)}")
            return {"rating": "div[class*='rating']"}

    def get_code_from_claude(self, user_command):
        """Send the user command to Claude API and get back Python code"""
        try:
            prompt = f"""
            Generate Python code for browser automation using Selenium based on this user command: "{user_command}"

            Only return valid, working Python code that assumes these variables are available:
            - 'browser': A selenium webdriver instance that's already initialized
            - 'random_sleep': A method for random delays (e.g., random_sleep(1, 3))
            - 'wait_for_page_load': A method to wait for page load completion
            - 'handle_popups': A method to close popups/overlays

            Use the latest Selenium 4+ syntax:
            - Import `from selenium.webdriver.common.by import By` and use `browser.find_element(By.ID, 'value')`.
            - For GitHub login, target `input#login_field` for username, `input#password` for password, `input[type='submit'][value='Sign in']` for login button.
            - For GitHub star button, try `button[aria-label*='Star this repository']`, `button.js-toggler-target`, `form#repo-stars-counter-star button`.

            Include ALL necessary import statements at the top, including:
            - `from selenium.webdriver.common.by import By`
            - `from selenium.webdriver.support.ui import WebDriverWait`
            - `from selenium.webdriver.support import expected_conditions as EC`
            - `from selenium.webdriver.common.action_chains import ActionChains`
            - `from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException`
            - `import logging`
            - `import time`
            - `import random`

            For robust automation:
            - Setup logging with `logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')`.
            - Log every step (e.g., navigation, element interaction, errors).
            - Save screenshots on errors with `browser.save_screenshot(f'error_{{error_type}}_{{int(time.time())}}.png')`.
            - Use `WebDriverWait` for all element interactions with at least 10-second timeouts.
            - Verify actions (e.g., after login, check for `img.avatar-user`; after starring, check `button[aria-label*='Unstar']`).
            - Call `wait_for_page_load` and `handle_popups` after navigation or major actions.
            - Use `ActionChains` for reliable clicks on interactive elements.
            - Implement JavaScript fallback clicks (`browser.execute_script('arguments[0].click();', element)`).
            - Use multiple selector strategies for critical elements with retries (max 3 attempts).
            - Use `random_sleep` after interactions to handle dynamic content.
            - Wrap code in a try-except block catching `TimeoutException`, `NoSuchElementException`, `StaleElementReferenceException`, and a general `Exception`.
            - Clean up with `random_sleep(2, 5)` in a `finally` block.
            - Do NOT wrap the code in a function definition; provide raw executable code that runs directly.

            For GitHub-specific tasks:
            - Verify login success by checking for `img.avatar-user` or `a[href*='/username']`.
            - For starring a repository, confirm the action by checking `button[aria-label*='Unstar']` or star count update.

            Return ONLY the raw Python code as plain text. Do NOT include Markdown code block markers, comments, explanations, function definitions, or any other formatting—just the executable code.
            """
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1500,
                temperature=0,
                system="You are an expert in Selenium automation.",
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            logging.error(f"Error getting code from Claude: {str(e)}")
            return None

    def execute_code(self, code):
        """Execute the generated Python code"""
        if not code:
            logging.error("No code was generated")
            return "No code was generated."
        try:
            local_vars = {
                "browser": self.browser,
                "random_sleep": self.random_sleep,
                "wait_for_page_load": self.wait_for_page_load,
                "handle_popups": self.handle_popups
            }
            required_vars = ["browser", "random_sleep", "wait_for_page_load", "handle_popups"]
            for var in required_vars:
                if not local_vars.get(var):
                    logging.error(f"Required variable '{var}' is not initialized")
                    return f"Error: Required variable '{var}' is not initialized"
            logging.debug(f"Executing code with variables: {list(local_vars.keys())}")
            if "random_sleep" not in code:
                logging.warning("Generated code does not use random_sleep; may rely on time.sleep")
            exec(code, {"__builtins__": __builtins__}, local_vars)
            logging.info("Code executed successfully")
            return "Code executed successfully"
        except NameError as e:
            logging.error(f"NameError in generated code: {str(e)}")
            return f"Error: NameError in generated code: {str(e)}"
        except Exception as e:
            logging.error(f"Error executing code: {str(e)}")
            return f"Error executing code: {str(e)}"

    def run_command(self, user_command):
        """Process user command through Claude and execute the resulting code"""
        logging.info(f"Processing command: {user_command}")
        code = self.get_code_from_claude(user_command)
        if code:
            logging.info("Generated code:")
            logging.info("-" * 18)
            logging.info(code)
            logging.info("-" * 18)
            code_filename = f"generated_code_{int(time.time())}.py"
            with open(code_filename, "w") as f:
                f.write(code)
            logging.info(f"Saved generated code to {code_filename}")
            result = self.execute_code(code)
            logging.info(f"Execution result: {result}")
            return result
        else:
            logging.error("Failed to generate code")
            return "Failed to generate code"

    def close(self):
        """Close the browser"""
        if self.browser:
            try:
                self.browser.quit()
                logging.info("Browser closed")
            except Exception as e:
                logging.error(f"Error closing browser: {str(e)}")
            self.browser = None

def main():
    api_key = ""
    automation = BrowserAutomation(api_key)
    try:
        while True:
            print("\nWhat would you like to do?")
            print("1. Extract data from a webpage")
            print("2. Run a browser automation command (executes within initialized browser)")
            print("3. Exit")
            choice = input("Enter your choice (1-3): ")
            if choice == "1":
                url = input("Enter the URL to extract data from: ")
                request = input("What data would you like to extract? (e.g., 'rating, reviews'): ")
                rules = automation.get_extraction_rules_from_claude(url, request)
                print("\nGenerated extraction rules:")
                print(json.dumps(rules, indent=2))
                result = automation.extract_data(url, rules)
                automation.last_result = result
                print("\nExtracted data:")
                print(json.dumps(result, indent=2))
            elif choice == "2":
                user_command = input("Enter browser automation command: ")
                result = automation.run_command(user_command)
                print(result)
            elif choice == "3":
                print("Exiting...")
                break
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")
    except KeyboardInterrupt:
        print("Program interrupted by user")
    finally:
        automation.close()

if __name__ == "__main__":
    main()