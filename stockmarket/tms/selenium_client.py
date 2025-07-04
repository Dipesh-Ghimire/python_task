from typing import Literal
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException
import time
import logging

from stockmarket import settings
logger = logging.getLogger("tms")

class SeleniumTMSClient:
    def __init__(self, broker_number, headless=True):
        self.chromedriver_path =settings.CHROMEDRIVER_PATH
        self.broker_number = broker_number
        self.username = None
        self.password = None
        self.driver = self._init_driver(headless)
        self.headless = headless
        self.base_url = f"https://tms{self.broker_number}.nepsetms.com.np"
        self.login_url = f"https://tms{self.broker_number}.nepsetms.com.np/login"
        self.order_url = f"https://tms{self.broker_number}.nepsetms.com.np/tms/me/memberclientorderentry"
        self.order_book_url = f"{self.base_url}/tms/me/order-book-v3"
        self.dp_holding_url = f"{self.base_url}/tms/me/dp-holding"
        self.portfolio_data = []
        self.eligible_portfolio = []
        self.order_entry_visited = False
        self.tracking_symbol = ["RURU", "NICA"]
        self.latest_scraped_data = {}
        self.stop_scraping_flag = False
        self.wait = WebDriverWait(self.driver, 10)

    def _init_driver(self, headless):
        options = Options()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        prefs = {"profile.managed_default_content_settings.images": 1,
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.stylesheets": 2,
                "profile.default_content_setting_values.javascript": 1}
        options.add_experimental_option("prefs", prefs)

        service = Service(self.chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver

    def open_login_page(self):
        self.driver.get(self.login_url)
        time.sleep(2)

    def get_captcha_base64(self):
        captcha_img = self.driver.find_element(By.TAG_NAME, "img")
        return captcha_img.screenshot_as_base64

    def fill_credentials(self, username, password):
        self.username = username
        self.password = password

    def submit_login(self, captcha_text):
        self.driver.find_element(By.XPATH, "//input[@placeholder='Client Code/ User Name']").clear()
        self.driver.find_element(By.XPATH, "//input[@placeholder='Client Code/ User Name']").send_keys(self.username)
        self.driver.find_element(By.XPATH, "//input[@placeholder='Password']").send_keys(self.password)
        self.driver.find_element(By.ID, "captchaEnter").send_keys(captcha_text)
        self.driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(3)

    def login_successful(self):
        return "dashboard" in self.driver.current_url

    def get_new_captcha(self):
        return self.get_captcha_base64()

    def close(self):
        self.driver.quit()
    
    def scrape_dashboard_stats(self):
        data = {
            "turnover": "",
            "traded_shares": "",
            "transactions": "",
            "scrips": ""
        }

        try:
            wait = WebDriverWait(self.driver, 15)

            # Wait until the card with the header "Market Summary" is visible
            market_summary_card = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[contains(@class, 'card-title') and normalize-space(text())='Market Summary']/ancestor::div[contains(@class, 'card')]")
                )
            )

            # Scrape the total turnover (inside h4)
            turnover = market_summary_card.find_element(By.CLASS_NAME, "h4").text.strip()
            data["turnover"] = turnover

            # Get all three key stats
            figures = market_summary_card.find_elements(By.CLASS_NAME, "figure")

            if len(figures) >= 3:
                data["traded_shares"] = figures[0].find_element(By.CLASS_NAME, "figure-value").text.strip()
                data["transactions"] = figures[1].find_element(By.CLASS_NAME, "figure-value").text.strip()
                data["scrips"] = figures[2].find_element(By.CLASS_NAME, "figure-value").text.strip()
            else:
                logger.info("⚠️ Not enough figure elements found.")

        except Exception as e:
            logger.info("Error scraping dashboard: %s", e)

        return data

    def scrape_collateral(self):
        data = {
            "collateral_utilized": "",
            "collateral_available": ""
        }

        try:
            wait = WebDriverWait(self.driver, 15)

            # Wait until the "Collateral Utilized" label is present
            utilized_value_elem = wait.until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//span[contains(text(), 'Collateral Utilized')]/following-sibling::span"
                ))
            )
            data["collateral_utilized"] = utilized_value_elem.text.strip()

            # Wait until the "Collateral Available" label is present
            available_value_elem = wait.until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//a[@id='collateralView']//following-sibling::span"
                ))
            )
            data["collateral_available"] = available_value_elem.text.strip()

        except Exception as e:
            logger.info("Error scraping collateral data: %s", e)

        return data

    def execute_trade(self, script_name: str, transaction: Literal['Buy', 'Sell'], quantity: int, price: float):
        try:
            self.enter_trade_details(quantity, price)

            # Extract LTP
            ltp = self.extract_ltp()
            logger.info(f"Trade executing: {transaction} {script_name} at :{ltp}:")


            if transaction == 'Buy':
                self.click_buy_button()
            else:
                self.click_sell_button()

            # # Wait briefly for the toast to appear
            # wait = WebDriverWait(self.driver, 0.5)
            # toast = wait.until(EC.presence_of_element_located(
            #     (By.CSS_SELECTOR, "div.toast-text.ng-star-inserted"))
            # )

            # # Extract toast title and message
            # toast_title = toast.find_element(By.CSS_SELECTOR, "span.toast-title").text.strip()
            # toast_msg = toast.find_element(By.CSS_SELECTOR, "span.toast-msg").text.strip()

            # msg = self.wait_for_toast()
            # if "Success" in msg:
            #     print("Trade executed successfully.")
            # elif "INVALID_ORDER_QUANTITY" in msg or "Invalid quantity" in msg:
            #     print("Trade failed: Invalid quantity.")
            # elif "Price should be within valid range" in msg:
            #     print("Trade failed: Price out of allowed range.")
            # else:
            #     print("⚠️ Unknown toast message:", msg)

        except Exception as e:
            logger.info("Error executing trade: %s", e)

    def enter_trade_details(self, quantity, price):
        try:
            wait = WebDriverWait(self.driver, 10)

            # Wait for and enter Quantity
            qty_input = wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[@formcontrolname='quantity']"))
            )
            qty_input.clear()
            qty_input.send_keys(str(quantity))

            # Wait for and enter Price
            price_input = wait.until(
                EC.presence_of_element_located((By.XPATH, "//input[@formcontrolname='price']"))
            )
            price_input.clear()
            price_input.send_keys(str(price))
            logger.info(f"Entered trade details: Quantity={quantity}, Price={price}")

        except Exception as e:
            logger.info("Error entering trade details: %s", e)
    
    def extract_stock_data(self):
        data = {
            "ltp": "",
            "change": "",
            "low": "",
            "high": "",
            "open": "",
            "day_high": "",
            "day_low": "",
            "avg_price": "",
            "pre_close": "",
            "52w_high": "",
            "52w_low": ""
        }

        try:
            wait = WebDriverWait(self.driver, 10)

            # Get all 'order__form--prodtype' containers
            elements = wait.until(
                EC.presence_of_all_elements_located((By.CLASS_NAME, "order__form--prodtype"))
            )

            for el in elements:
                label = el.find_element(By.CLASS_NAME, "order__form--label").text.strip()
                value = ""

                # LTP is not inside a <b> or <span>, it’s a direct text node — extract manually
                if label == "LTP":
                    full_text = el.text.strip()
                    value = full_text.split("\n")[1].strip() if "\n" in full_text else full_text.replace("LTP", "").strip()
                    change_elem = el.find_elements(By.CLASS_NAME, "change-price")
                    data["change"] = change_elem[0].text.strip() if change_elem else ""
                    data["ltp"] = value

                else:
                    # For all others, the value is inside <b>
                    try:
                        value = el.find_element(By.TAG_NAME, "b").text.strip()
                    except:
                        value = ""

                    # Map label to the corresponding key
                    mapping = {
                        "Low": "low",
                        "High": "high",
                        "Open": "open",
                        "D High": "day_high",
                        "D Low": "day_low",
                        "Avg Price": "avg_price",
                        "Pre Close": "pre_close",
                        "52W High": "52w_high",
                        "52W Low": "52w_low"
                    }

                    if label in mapping:
                        data[mapping[label]] = value

        except Exception as e:
            logger.info("Error extracting stock data: %s", e)

        return data

    def extract_ltp(self) -> float:
        raw_ltp =  self.extract_stock_data().get("ltp", "").replace(",", "")
        # raw ltp = '723 (2.3)'
        # Extract only the numeric part
        ltp = raw_ltp.split(" ")[0] if raw_ltp else "0"
        return float(ltp)

    def extract_market_depth(self):
        market_depth = {
            "buy": [],   # List of dicts: [{"order": ..., "qty": ..., "price": ...}]
            "sell": []   # List of dicts: [{"price": ..., "qty": ..., "order": ...}]
        }

        try:
            wait = WebDriverWait(self.driver, 10)

            # Get all tables (Top 5 Buy is first, Top 5 Sell is second)
            tables = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "table.table--data"))
            )

            # --- Extract Buy Side ---
            buy_rows = tables[0].find_elements(By.CSS_SELECTOR, "tbody tr.text-buy")
            for row in buy_rows:
                cols = row.find_elements(By.CLASS_NAME, "text-center")
                if len(cols) == 3:
                    market_depth["buy"].append({
                        "order": cols[0].text.strip(),
                        "qty": cols[1].text.strip(),
                        "price": cols[2].text.strip()
                    })

            # --- Extract Sell Side ---
            sell_rows = tables[1].find_elements(By.CSS_SELECTOR, "tbody tr.text-sell")
            for row in sell_rows:
                cols = row.find_elements(By.CLASS_NAME, "text-center")
                if len(cols) == 3:
                    market_depth["sell"].append({
                        "price": cols[0].text.strip(),
                        "qty": cols[1].text.strip(),
                        "order": cols[2].text.strip()
                    })

        except Exception as e:
            logger.info("Error extracting market depth: %s", e)

        return market_depth

    def click_buy_button(self):
        try:
            wait = WebDriverWait(self.driver, 10)

            # Locate the BUY button (with both "btn-primary" and text "BUY")
            buy_button = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH, "//button[contains(@class, 'btn-primary') and normalize-space(text())='BUY']"
                ))
            )

            buy_button.click()
            logger.info("BUY button clicked successfully.")

        except Exception as e:
            logger.info("Failed to click BUY button: %s", e)

    def click_sell_button(self):
        try:
            sell_button = self.driver.find_element(By.XPATH, "//button[contains(text(), 'SELL')]")
            sell_button.click()
            logger.info("Sell button clicked.")
        except Exception as e:
            logger.info("Error clicking sell button: %s", e)

    def wait_for_toast(self, timeout=10) -> str:
        try:
            wait = WebDriverWait(self.driver, timeout)
            toast_container = wait.until(EC.presence_of_element_located((By.ID, "toasty")))

            # Wait for any visible toast inside the container
            toast = toast_container.find_element(By.CLASS_NAME, "toast-text")
            title = toast.find_element(By.CLASS_NAME, "toast-title").text
            message = toast.find_element(By.CLASS_NAME, "toast-msg").text

            full_message = f"{title}: {message}"
            print("🔔 Toast:", full_message)
            return full_message

        except TimeoutException:
            print("⏰ Toast message did not appear in time.")
            return "Timeout"

        except Exception as e:
            print(f"❌ Error while parsing toast: {e}")
            return "Error"

    def go_to_market_depth(self):
        try:
            wait = WebDriverWait(self.driver, 10)

            # Step 1: Click "Market Data"
            market_data_menu = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[.//span[contains(text(), 'Market Data')]]")
            ))
            market_data_menu.click()

            # Step 2: Wait for and click "Market Depth"
            market_depth_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//li[contains(@class, 'menu__dropdown')]//a[.//span[contains(text(), 'Market  Depth')]]")
            ))
            market_depth_link.click()

            logger.info("✅ Navigated to Market Depth")

            return True

        except TimeoutException:
            logger.info("❌ Could not navigate to Market Depth")
            return False

    def get_market_depth_html(self, instrument_type: str, script_name: str) -> str:
        try:
            wait = WebDriverWait(self.driver, 15)

            # Step 1: Go to Market Depth
            self.go_to_market_depth()

            # Step 2: Select Instrument Type
            instrument_dropdown = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "select[formcontrolname='instrumentType']")
            ))
            select = Select(instrument_dropdown)
            select.select_by_visible_text(instrument_type.upper())
            logger.info(f"✅ Selected Instrument Type: {instrument_type}")

            time.sleep(2)  # allow scripts to reload based on instrument

            # Step 3: Search and Select Script
            search_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "ng-select[formcontrolname='security'] input[type='text']"))
            )
            search_input.click()
            search_input.clear()
            search_input.send_keys(script_name)
            time.sleep(2)  # wait for dropdown options to appear

            search_input.send_keys(Keys.ENTER)  # select top option
            logger.info(f"✅ Selected Script: {script_name}")

            # Step 4: Wait for market depth table to load
            table = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "table.market__depth__general-info"))
            )
            logger.info("✅ Market depth table loaded")

            return table.get_attribute("outerHTML")

        except TimeoutException as e:
            logger.info("❌ Failed to load market depth")
            return "<p>Error: Could not retrieve market depth</p>"

    def go_to_place_order(self, script_name, transaction: Literal['Buy', 'Sell']):
        try:
            if transaction not in ('Buy', 'Sell'):
                raise ValueError("Transaction must be either 'Buy' or 'Sell'")
            url = self.order_url+f"?symbol={script_name}&transaction={transaction}"
            self.driver.get(url)
            time.sleep(2)
        except Exception as e:
            logger.info(f"Failed to navigate to place order page: {e}")
            return False

    def go_to_order_entry(self):
        try:
            self.driver.get(self.order_url)
            time.sleep(2)
        except Exception as e:
            logger.info(f"Failed to navigate to order entry page: {e}")
            return False

    def scrape_multiple_stocks(self, symbols=None):
        """
        Scrapes market depth data for multiple symbols.
        """
        if symbols is None:
            symbols = self.tracking_symbol
        for symbol in symbols:
            self.scrape_top_depth_for_symbol(symbol)
            time.sleep(0.5)
        return True
    
    def scrape_top_depth_for_symbol(self, symbol_name):
        """
        Scrapes top buyer and seller for a given stock symbol, with retry logic for stale elements.
        """
        # if flag is true, then stop scraping
        if self.stop_scraping_flag:
            logger.info(f"Stopping scraping as per flag.")
            return
        try:
            # Clear and enter symbol
            symbol_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='symbol']"))
            )
            symbol_input.clear()
            symbol_input.send_keys(symbol_name)
            time.sleep(2)
            symbol_input.send_keys(Keys.ENTER)
            time.sleep(2)

            result = {
                "top_buyer": {"price": None, "quantity": None},
                "top_seller": {"price": None, "quantity": None},
                "error": None
            }

            def safe_extract_depth():
                depth_section = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.col-md-5.col-sm-12"))
                )

                # --- Buy side ---
                buy_rows = depth_section.find_elements(By.CSS_SELECTOR, "tr.text-buy")
                if not buy_rows:
                    buy_rows = depth_section.find_elements(By.XPATH, ".//tr[contains(@class, 'text-buy')]")

                if buy_rows:
                    cells = buy_rows[0].find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 3:
                        result["top_buyer"]["quantity"] = int(cells[1].text.strip())
                        result["top_buyer"]["price"] = float(cells[2].text.strip())

                # --- Sell side ---
                sell_rows = depth_section.find_elements(By.CSS_SELECTOR, "tr.text-sell")
                if not sell_rows:
                    sell_rows = depth_section.find_elements(By.XPATH, ".//tr[contains(@class, 'text-sell')]")

                if sell_rows:
                    cells = sell_rows[0].find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 2:
                        result["top_seller"]["price"] = float(cells[0].text.strip())
                        result["top_seller"]["quantity"] = int(cells[1].text.strip())

            # Try scraping up to 2 times in case of stale element
            for attempt in range(2):
                try:
                    safe_extract_depth()
                    break
                except StaleElementReferenceException as e:
                    logger.warning(f"Retry {attempt + 1} due to stale element for {symbol_name}")
                    time.sleep(1)
                except Exception as e:
                    result["error"] = f"Scraping error: {str(e)}"
                    logger.error(f"Scraping error for {symbol_name}: {str(e)}")
                    break

            logger.info(f"Scraped data for {symbol_name}: {result}")
            self.latest_scraped_data[symbol_name] = result  # Update latest scraped data
            return

        except Exception as e:
            error_msg = f"Failed for {symbol_name}: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def get_latest_data(self):
        return self.latest_scraped_data
    
    def switch_tab(self,tab_name="Open"):
        """
        Clicks the appropriate tab (Open or Completed) and waits for it to activate.
        """
        tab_id = {
            "Open": "nav-open-info-tab",
            "Completed": "nav-completed-info-tab"
        }[tab_name]

        tab = self.driver.find_element(By.ID, tab_id)
        tab.click()

        # Wait until this tab is active
        self.wait.until(EC.element_to_be_clickable((By.ID, tab_id)))
    
    def set_page_size_to_all(self):
        try:
            # Wait for the page size dropdown to be present
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "kendo-pager-page-sizes select"))
            )

            # Find the page size dropdown
            page_size_dropdown = self.driver.find_element(By.CSS_SELECTOR, "kendo-pager-page-sizes select")

            # Select the "All" option
            select = Select(page_size_dropdown)
            select.select_by_visible_text("All")

            # Wait for the grid to reload with all records
            WebDriverWait(self.driver, 10).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div.k-loading-mask"))
            )
        except Exception as e:
            logger.error(f"Error setting page size to All: {e}")
    
    def scrape_open_orders(self):
        self.driver.get(self.order_book_url)
        time.sleep(2)
        try:
            # Default to Open tab
            self.set_page_size_to_all()
            # Wait for the grid to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "k-grid-table"))
            )
            
            # Find all order rows - they have class "k-master-row"
            order_rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.k-master-row")
            
            orders = []
            
            for row in order_rows:
                # Extract data from each cell in the row
                cells = row.find_elements(By.TAG_NAME, "td")
                
                # Skip the first two cells (hierarchy and checkbox)
                order_data = {
                    "S.N": cells[2].text.strip(),
                    "ACTION": cells[3].text.strip(),
                    "STATUS": cells[4].text.strip(),
                    "CLIENT": cells[5].text.strip(),
                    "CLIENT_NAME": cells[6].text.strip(),
                    "SYMBOL": cells[7].text.strip(),
                    "TYPE": cells[8].text.strip(),
                    "QTY": cells[9].text.strip(),
                    "TRADED_QTY": cells[10].text.strip(),
                    "PRICE(NPR)": cells[11].text.strip(),
                    "REM_QTY": cells[12].text.strip(),
                    "VALUE": cells[13].text.strip(),
                    "EXCHANGE_ORDER_ID": cells[14].text.strip(),
                    "ORDER_TIME": cells[15].text.strip(),
                    "ORDER_PLACED_BY": cells[16].text.strip()
                }
                orders.append(order_data)
            # print all orders in loop
            for order in orders:
                print(order)
            logger.info(f"Scraped {len(orders)} open orders.")
            return orders
        except Exception as e:
            logger.error(f"Error scraping open orders: {e}")
            return []
        
    def scrape_completed_orders(self):
        self.driver.get(self.order_book_url)
        time.sleep(2)
        try:
            self.switch_tab("Completed")
            # Default to Open tab
            self.set_page_size_to_all()
            # Wait for the grid to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "k-grid-table"))
            )
            
            # Find all order rows - they have class "k-master-row"
            order_rows = self.driver.find_elements(By.CSS_SELECTOR, "tr.k-master-row")
            completed_orders = []
            for row in order_rows:
                # Check if the order is completed (CANCELLED)
                status_cell = row.find_elements(By.TAG_NAME, "td")[2]  # STATUS is the 3rd column (index 2)
                status = status_cell.text.strip()
                # Extract data from each cell in the row
                cells = row.find_elements(By.TAG_NAME, "td")
                
                order_data = {
                    "S.N": cells[1].text.strip(),  # Index 1 (2nd column)
                    "STATUS": status,
                    "CLIENT": cells[3].text.strip(),
                    "CLIENT_NAME": cells[4].text.strip(),
                    "SYMBOL": cells[5].text.strip(),
                    "TYPE": cells[6].text.strip(),
                    "QTY": cells[7].text.strip(),
                    "TRADED_QTY": cells[8].text.strip(),
                    "PRICE(NPR)": cells[9].text.strip(),
                    "REM_QTY": cells[10].text.strip(),
                    "VALUE": cells[11].text.strip(),
                    "EXCHANGE_ORDER_ID": cells[12].text.strip(),
                    "ORDER_TIME": cells[13].text.strip(),
                    "ORDER_PLACED_BY": cells[14].text.strip()
                }
                completed_orders.append(order_data)
            # print all orders in loop
            for order in completed_orders:
                print(order)
            logger.info(f"Scraped {len(completed_orders)} Completed orders.")
            return completed_orders
        except Exception as e:
            logger.error(f"Error scraping Completed orders: {e}")
            return []
        
    def cancel_all_open_orders(self):
        """
        Cancels all open orders for the logged-in user.
        Returns a JSON response indicating success or failure.
        """
        try:
            self.driver.get(self.order_book_url)
            time.sleep(2)
            self.set_page_size_to_all()
            # Wait for the grid to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "k-grid-table"))
            )
            
            checkbox = self.wait.until(EC.presence_of_element_located((By.ID, "k-grid0-select-all")))

            # Use JavaScript to set the checkbox and trigger the change event
            self.driver.execute_script("""
                const checkbox = arguments[0];
                if (!checkbox.checked) {
                    checkbox.click(); // This is important for UI sync
                    const event = new Event('change', { bubbles: true });
                    checkbox.dispatchEvent(event);
                }
            """, checkbox)
            logger.info("Checkbox clicked and change event dispatched.")
            
            cancel_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Cancel Selected Orders']")))
            cancel_button.click()
            
            # Wait for modal to be visible
            time.sleep(1)
            self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "modal-dialog")))
            # yes_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Yes')]")))
            modal_footer = self.driver.find_element(By.CLASS_NAME, "modal-footer")
            yes_button = modal_footer.find_element(By.XPATH, ".//button[normalize-space(text())='Yes']")

            try:
                yes_button.click()
                logger.info("Clicked 'Yes' button successfully.")
            except Exception as click_err:
                logger.warning(f"Standard click failed: {click_err}, using JavaScript fallback.")
                self.driver.execute_script("arguments[0].click();", yes_button)
                logger.info("Clicked 'Yes' button using JS fallback.")
            
            logger.info("All open orders cancelled successfully.")
            return {"success": True, "message": "All open orders cancelled successfully."}
        except Exception as e:
            logger.error(f"Error cancelling open orders: {e}")
            return {"error": str(e)}
        
    def scrape_dp_holding(self):
        try:
            self.driver.get(self.dp_holding_url)
            time.sleep(5)
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.k-grid-content table.k-grid-table")))
            rows = self.driver.find_elements(By.CSS_SELECTOR, "table.k-grid-table tbody tr")
            self.portfolio_data = []
            for row in rows:
                try:
                    # Extract data from each column
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) >= 9:
                        data = {
                            'symbol': cells[1].find_element(
                                By.CSS_SELECTOR, "span.table--view").text.strip(),
                            'cds_total_balance': cells[2].text.strip(),
                            'cds_free_balance': cells[3].text.strip(),
                            'tms_balance': cells[4].text.strip(),
                            'ltp': cells[7].text.strip(),
                        }
                        self.portfolio_data.append(data)

                        self.eligible_portfolio = [ {**item, 'selling_quantity': int(item['cds_free_balance'])} for item in self.portfolio_data if int(item['cds_free_balance']) > 19 ]
                except (NoSuchElementException, IndexError) as e:
                    logger.warning(f"Error parsing row: {e}")
                    continue
            logger.info(f"Scraped DP holding data for {len(self.portfolio_data)} stocks.")

        except Exception as e:
            logger.error(f"Error scraping DP holding: {e}")
            return {"error": str(e)}
        
    def sell_full_portfolio(self):
        """
        Sells all stocks in the portfolio.
        """
        self.scrape_dp_holding()  # Ensure portfolio data is up-to-date
        if not self.eligible_portfolio:
            logger.info("No eligible stocks to sell.")
            return {"error": "No eligible stocks to sell."}

        for stock in self.eligible_portfolio:
            try:
                self.go_to_place_order(stock['symbol'], 'Sell')
                quantity = stock['selling_quantity']
                price = float(stock['ltp'].replace(',', ''))  # Convert LTP to float
                self.execute_trade(stock['symbol'], 'Sell', quantity, price)
                logger.info(f"Sell Order Placed {quantity} shares of {stock['symbol']} at {price}.")
            except Exception as e:
                logger.error(f"Error selling {stock['symbol']}: {e}")
    
    def sell_half_portfolio(self):
        """
        Sells half of the eligible stocks in the portfolio.
        """
        self.scrape_dp_holding()  # Ensure portfolio data is up-to-date
        if not self.eligible_portfolio:
            logger.info("No eligible stocks to sell.")
            return {"error": "No eligible stocks to sell."}

        for stock in self.eligible_portfolio:
            try:
                self.go_to_place_order(stock['symbol'], 'Sell')
                quantity = stock['selling_quantity'] // 2
                price = float(stock['ltp'].replace(',', ''))  # Convert LTP to float
                self.execute_trade(stock['symbol'], 'Sell', quantity, price)
                logger.info(f"Sell Order Placed {quantity} shares of {stock['symbol']} at {price}.")
            except Exception as e:
                logger.error(f"Error selling {stock['symbol']}: {e}")