import requests
import json
import anthropic
import time
import random
import re
import logging
from bs4 import BeautifulSoup
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import os
from crontab import CronTab
import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')


class BrowserAutomationWithScraper:
    def __init__(self, api_key=None):
        # Set up API key
        self.api_key = api_key
        if not self.api_key:
            # Try to load from environment variables
            load_dotenv()
            self.api_key = os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            logging.error("No API key provided. You'll need to set one before querying Claude.")
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

        # Initialize browser
        self.browser = None
        self.last_result = None
        self.setup_browser()

        # Initialize web scraping attributes
        self.current_url = None
        self.soup = None
        self.content = ""
        self.structured_data = {}

        # Initialize conversation history
        self.conversation_history = []
        self.conversation_context = {
            "visited_urls": [],
            "extracted_sites": [],
            "last_command": None,
            "last_query": None,
            "session_start": datetime.datetime.now()
        }

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

    def get_code_from_claude(self, user_command):
        """Send the user command to Claude API and get back Python code"""
        try:
            # Include conversation context in the prompt
            context_str = self._format_context_for_prompt()

            # Check for scheduling keywords in the user command
            scheduling_indicators = ["schedule", "cron", "later", "daily", "weekly", "monthly", "every", "periodic",
                                     "timer"]
            should_schedule = any(indicator in user_command.lower() for indicator in scheduling_indicators)

            prompt = f"""
            Generate Python code for browser automation using Selenium based on this user command: "{user_command}"

            CONVERSATION CONTEXT:
            {context_str}

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
            """

            # Add scheduling instructions if needed
            if should_schedule:
                prompt += f"""
                IMPORTANT: This task needs to be scheduled. Follow these additional requirements:
                - Import `from crontab import CronTab` and `import datetime`
                - Get the current time with `current_time = datetime.datetime.now()`
                - Extract the scheduling requirements from the user command
                - Create a Python script file that contains the automation code
                - Set up a cron job to run this script at the specified time using the python-crontab library
                - If no specific time is mentioned, set the task to run 5 minutes from now
                - Log scheduled information including the scheduled time and command

                Example cron job setup:
                ```python
                # Create script file
                script_filename = f"scheduled_task_{int(time.time())}.py"
                with open(script_filename, "w") as f:
                    f.write("#!/usr/bin/env python\\n")
                    f.write("import logging\\n")
                    f.write("# Rest of imports\\n\\n")
                    f.write("# Your automation code here\\n")

                # Make the script executable
                import os
                os.chmod(script_filename, 0o755)

                # Setup cron job
                cron = CronTab(user=True)
                job = cron.new(command=f"/usr/bin/python3 {os.path.abspath(script_filename)}")

                # Set schedule (examples)
                job.minute.on(30)  # Run at 30 minutes past the hour
                # OR
                job.setall('30 14 * * *')  # Run at 2:30 PM daily
                # OR
                job.every(1).day()  # Run daily

                # Write cron job to crontab
                cron.write()
                ```
                """

            prompt += """
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

    def _format_context_for_prompt(self):
        """Format the conversation context for inclusion in the prompt"""
        context_parts = []

        # Add current URL if available
        if self.browser and self.browser.current_url and self.browser.current_url != "about:blank":
            current_url = self.browser.current_url
            context_parts.append(f"Current browser URL: {current_url}")

        # Add visited URLs
        if self.conversation_context["visited_urls"]:
            visited_urls = ", ".join(self.conversation_context["visited_urls"][-5:])  # Last 5 URLs
            context_parts.append(f"Recently visited URLs: {visited_urls}")

        # Add last command if available
        if self.conversation_context["last_command"]:
            context_parts.append(f"Last command: {self.conversation_context['last_command']}")

        # Add session duration
        session_duration = datetime.datetime.now() - self.conversation_context["session_start"]
        duration_minutes = session_duration.total_seconds() / 60
        context_parts.append(f"Session duration: {duration_minutes:.1f} minutes")

        return "\n".join(context_parts)

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

            # Update context after executing code
            if self.browser and self.browser.current_url and self.browser.current_url != "about:blank":
                if self.browser.current_url not in self.conversation_context["visited_urls"]:
                    self.conversation_context["visited_urls"].append(self.browser.current_url)

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

        # Update context with the current command
        self.conversation_context["last_command"] = user_command

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_command,
            "timestamp": datetime.datetime.now().isoformat()
        })

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

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": result,
                "timestamp": datetime.datetime.now().isoformat()
            })

            logging.info(f"Execution result: {result}")
            return result
        else:
            error_msg = "Failed to generate code"

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": error_msg,
                "timestamp": datetime.datetime.now().isoformat()
            })

            logging.error(error_msg)
            return error_msg

    def extract_current_page_content(self):
        """Extract content from the current page in the browser"""
        if not self.browser:
            logging.error("Browser is not initialized")
            return False

        try:
            # Get the current URL
            self.current_url = self.browser.current_url
            logging.info(f"Extracting content from current page: {self.current_url}")

            # Get the page source
            page_source = self.browser.page_source
            self.soup = BeautifulSoup(page_source, 'html.parser')

            # Extract content
            result = self._extract_content_from_soup()

            # Update context if extraction was successful
            if result and self.current_url not in self.conversation_context["extracted_sites"]:
                self.conversation_context["extracted_sites"].append(self.current_url)

            return result
        except Exception as e:
            logging.error(f"Error extracting content from current page: {str(e)}")
            return False

    def _extract_content_from_soup(self):
        """Extract and organize content from BeautifulSoup object"""
        if not self.soup:
            logging.error("No soup object available")
            return False

        # Remove unwanted elements
        for script in self.soup(["script", "style", "meta", "noscript"]):
            script.extract()

        # Extract page title
        title = self.soup.title.string if self.soup.title else "No title found"

        # Extract main text content
        main_content = []

        # Extract headers
        headers = []
        for i in range(1, 7):
            for header in self.soup.find_all(f'h{i}'):
                text = header.get_text(strip=True)
                if text:
                    headers.append(f"{'#' * i} {text}")
                    main_content.append(f"{'#' * i} {text}")

        # Extract paragraphs
        paragraphs = []
        for p in self.soup.find_all('p'):
            text = p.get_text(strip=True)
            if text:
                paragraphs.append(text)
                main_content.append(text)

        # Extract lists
        lists = []
        for ul in self.soup.find_all(['ul', 'ol']):
            list_items = []
            for li in ul.find_all('li'):
                text = li.get_text(strip=True)
                if text:
                    list_items.append(f"- {text}")
            if list_items:
                lists.append(list_items)
                main_content.extend(list_items)

        # Extract tables
        tables = []
        for table in self.soup.find_all('table'):
            table_rows = []
            for tr in table.find_all('tr'):
                row = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if row:
                    table_rows.append(" | ".join(row))

            if table_rows:
                tables.append(table_rows)
                main_content.append("TABLE:")
                main_content.extend(table_rows)

        # Compile all content into a single string
        self.content = "\n\n".join(main_content)

        # Store structured data
        self.structured_data = {
            'title': title,
            'headers': headers,
            'paragraphs': paragraphs,
            'lists': lists,
            'tables': tables,
            'full_content': self.content
        }

        content_length = len(self.content)
        logging.info(f"Content extracted successfully ({content_length} characters)")
        logging.info(f"- {len(headers)} headers")
        logging.info(f"- {len(paragraphs)} paragraphs")
        logging.info(f"- {len(lists)} lists")
        logging.info(f"- {len(tables)} tables")

        return True

    def query_content(self, user_query, model="claude-3-haiku-20240307"):
        """Query Claude with the extracted content and user question"""
        if not self.api_key:
            logging.error("API key not set. Use set_api_key() method first.")
            return "API key not configured"

        if not self.content:
            return "No content has been extracted yet. Please extract content from the current page first."

        # Update context with the current query
        self.conversation_context["last_query"] = user_query

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": f"Question about page {self.current_url}: {user_query}",
            "timestamp": datetime.datetime.now().isoformat()
        })

        # Create system prompt with context and instructions
        system_prompt = f"""You are an assistant that answers questions based on the content of a webpage.
Below is the content scraped from: {self.current_url}

Your task is to answer the user's question based ONLY on this content.
If the answer isn't in the content, say you don't have that information.
Be concise but thorough, and cite specific parts of the content when appropriate.
"""

        # Truncate content if it's too long (Claude has token limits)
        max_content_length = 50000  # Conservative estimate for token limits
        truncated_content = self.content
        if len(self.content) > max_content_length:
            truncated_content = self.content[:max_content_length] + "\n[Content truncated due to length]"

        # Construct user message with content and query
        user_message = f"""WEBPAGE CONTENT:
{truncated_content}

MY QUESTION:
{user_query}"""

        try:
            # Query Claude API
            response = self.client.messages.create(
                model=model,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1024
            )

            answer = response.content[0].text

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": answer,
                "timestamp": datetime.datetime.now().isoformat()
            })

            return answer
        except Exception as e:
            error_msg = f"Error: Failed to get response from Claude API. {str(e)}"
            logging.error(f"Error querying Claude API: {str(e)}")

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": error_msg,
                "timestamp": datetime.datetime.now().isoformat()
            })

            return error_msg

    def save_content(self, filename="scraped_content.json"):
        """Save the structured content to a JSON file"""
        if not self.structured_data:
            logging.info("No content to save")
            return False

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.structured_data, f, indent=2)
            logging.info(f"Content saved to {filename}")
            return True
        except Exception as e:
            logging.error(f"Error saving content: {str(e)}")
            return False

    def save_conversation(self, filename="conversation_history.json"):
        """Save the conversation history to a JSON file"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "history": self.conversation_history,
                    "context": self.conversation_context
                }, f, indent=2)
            logging.info(f"Conversation history saved to {filename}")
            return True
        except Exception as e:
            logging.error(f"Error saving conversation history: {str(e)}")
            return False

    def set_api_key(self, api_key):
        """Set or update the Claude AI key"""
        self.api_key = api_key
        self.client = anthropic.Anthropic(api_key=api_key)
        logging.info("API key updated successfully")

    def close(self):
        """Close the browser"""
        if self.browser:
            try:
                self.browser.quit()
                logging.info("Browser closed")
            except Exception as e:
                logging.error(f"Error closing browser: {str(e)}")
            self.browser = None

    def process_natural_language_command(self, user_input):
        """Process a natural language command and determine the appropriate action"""
        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.datetime.now().isoformat()
        })

        # Define keywords for each type of action
        automation_keywords = ["go to", "navigate", "click", "fill", "search", "login", "download", "submit",
                               "automate", "browse"]
        extraction_keywords = ["extract", "scrape", "get content", "get text", "get data"]
        query_keywords = ["what", "who", "when", "where", "why", "how", "tell me", "explain", "find"]

        # Check if there's a current page and the input looks like a question about it
        has_current_page = self.current_url is not None and self.content
        looks_like_question = any(
            user_input.lower().startswith(kw.lower()) for kw in query_keywords) or user_input.endswith("?")

        if has_current_page and looks_like_question:
            # This appears to be a question about the current page
            logging.info(f"Processing as a query about the current page: {user_input}")
            response = self.query_content(user_input)
        elif any(kw.lower() in user_input.lower() for kw in extraction_keywords):
            # This appears to be a content extraction request
            logging.info(f"Processing as a content extraction request: {user_input}")
            if self.extract_current_page_content():
                response = f"Successfully extracted content from: {self.current_url}"
            else:
                response = "Failed to extract content. See logs for details."
        else:
            # Default to automation command
            logging.info(f"Processing as an automation command: {user_input}")
            response = self.run_command(user_input)

        # Add response to conversation history
        self.conversation_history.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.datetime.now().isoformat()
        })

        return response


def main():
    print("=" * 60)
    print("Claude-Powered Web Automation & Scraper - Conversational".center(60))
    print("=" * 60)

    # Initialize the automation with scraper
    api_key = input("Enter your Claude API key (press Enter to use environment variable): ").strip() or None
    automation = BrowserAutomationWithScraper(api_key)

    try:
        print("\nWelcome to the conversational web automation assistant!")
        print("You can give natural language commands like:")
        print("- 'Go to github.com'")
        print("- 'Extract content from this page'")
        print("- 'What is this page about?'")
        print("- 'Search for Python tutorials on Google'")
        print("\nType 'exit', 'quit', or 'bye' to end the session.")

        while True:
            print("\n" + "-" * 60)
            user_input = input("\nWhat would you like me to do? ").strip()

            if user_input.lower() in ['exit', 'quit', 'bye']:
                print("\nSaving conversation history...")
                automation.save_conversation()
                print("\nThank you for using the Claude-Powered Web Automation & Scraper!")
                break

            if user_input.lower() == 'help':
                print("\nCommands you can use:")
                print("- Browser automation: 'Go to [URL]', 'Click on [element]', etc.")
                print("- Content extraction: 'Extract content from this page'")
                print("- Querying content: Ask any question about the current page")
                print("- Save content: 'Save the extracted content'")
                print("- Save history: 'Save conversation history'")
                print("- Exit: 'exit', 'quit', or 'bye'")
                continue

            if user_input.lower() == 'save content' and automation.structured_data:
                filename = input(
                    "Enter filename to save content (default: scraped_content.json): ").strip() or "scraped_content.json"
                automation.save_content(filename)
                continue

            if user_input.lower() == 'save history':
                filename = input(
                    "Enter filename to save conversation history (default: conversation_history.json): ").strip() or "conversation_history.json"
                automation.save_conversation(filename)
                continue

            if not user_input:
                continue

            print("\nProcessing your request...")
            result = automation.process_natural_language_command(user_input)
            print("\nResult:")
            print("-" * 60)
            print(result)
            print("-" * 60)

    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    finally:
        # Save conversation history on exit
        automation.save_conversation()
        automation.close()


if __name__ == "__main__":
    main()