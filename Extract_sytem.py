#!/usr/bin/env python
# coding: utf-8

# In[1]:


# !pip install pytesseract
# !pip install PyPDF2
# !apt install tesseract-ocr
# !pip install pytesseract pdf2image
# !apt update
# !apt install poppler-utils
# !pip install pdf2image
# !pip install stanza


# In[2]:


import threading
import re
import spacy
from spacy.matcher import Matcher
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, PhotoImage
from pdf2image import convert_from_path
from ttkthemes import ThemedTk, ThemedStyle
from tkinter.ttk import Progressbar, Style
import pytesseract
import atexit
import os
import stanza
import dateparser
import csv
from PIL import Image, ImageTk
import datefinder
import Quartz
import Vision
from Cocoa import NSURL
from Foundation import NSDictionary
# needed to capture system-level stderr
from wurlitzer import pipes
import time


# In[3]:


pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'


# In[4]:


""" Use Apple's Vision Framework via PyObjC to detect text in images """


def image_to_text(img_path, lang="eng"):
    input_url = NSURL.fileURLWithPath_(img_path)

    with pipes() as (out, err):
    # capture stdout and stderr from system calls
    # otherwise, Quartz.CIImage.imageWithContentsOfURL_
    # prints to stderr something like:
    # 2020-09-20 20:55:25.538 python[73042:5650492] Creating client/daemon connection: B8FE995E-3F27-47F4-9FA8-559C615FD774
    # 2020-09-20 20:55:25.652 python[73042:5650492] Got the query meta data reply for: com.apple.MobileAsset.RawCamera.Camera, response: 0
        input_image = Quartz.CIImage.imageWithContentsOfURL_(input_url)

    vision_options = NSDictionary.dictionaryWithDictionary_({})
    vision_handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(
        input_image, vision_options
    )
    results = []
    handler = make_request_handler(results)
    vision_request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
    error = vision_handler.performRequests_error_([vision_request], None)

    return results

def make_request_handler(results):
    """ results: list to store results """
    if not isinstance(results, list):
        raise ValueError("results must be a list")

    def handler(request, error):
        if error:
            print(f"Error! {error}")
        else:
            observations = request.results()
            for text_observation in observations:
                recognized_text = text_observation.topCandidates_(1)[0]
                results.append([recognized_text.string(), recognized_text.confidence()])
    return handler


# In[5]:


class TextExtractor:
    def __init__(self, root):
        self.root = root
        self.root.title('Choose File')
        self.image = Image.open("Bruntwood_icon.png")
        # Convert the image to a Tkinter-compatible format
        self.root.iconphoto(True, ImageTk.PhotoImage(self.image))
        self.root.geometry('400x200')
        self.extractor = Extractor()  # Create RentExtractor instance
        self.choose_file_page = ChooseFilePage(self.root, self.extractor)
        self.choose_file_page.setup_close_handler(self)  # Pass the TextExtractor instance to handle the closure
        
    def on_closing(self):
        # Custom function to handle the window closure
        if hasattr(self, "choose_file_page") and hasattr(self.choose_file_page, "display_text_page"):
            self.choose_file_page.display_text_page.destroy()  # Destroy the DisplayTextPage if it exists
        self.root.destroy()  # Close the main application window
        os._exit(0)
#         root.quit()


# In[6]:


class Extractor:
    def __init__(self):
        self.nlp = spacy.load('en_core_web_sm')
        self.stanza_nlp = stanza.Pipeline(processors='tokenize,ner', lang='en')
        self.matcher = Matcher(self.nlp.vocab)
        self.match_after = Matcher(self.nlp.vocab)
        self.match_before = Matcher(self.nlp.vocab)
        self.match_term = Matcher(self.nlp.vocab)
        self.info = {}
        self.initialize_matchers()

    def initialize_matchers(self):
        # Define the first search patterns
        rent_value_pattern = [
            {"LOWER": {"IN": ["annual", "initial"]}, "OP": "?"},
            {"LOWER": "rent"}
        ]
        term_pattern = [{"LOWER": "term"}]
        commencement_date_pattern = [{"LOWER": "term"}, {"LOWER": "commencement"}, {"LOWER": "date"}]
        review_date_pattern = [{"LOWER": "review"},{"LOWER":{"IN":["date", "date(s"]}}]
        lease_date_pattern = [{"LOWER": "date"}, {"LOWER": "of"}, {"LOWER": "lease"}]
        lease_date_pattern_2 = [{"LOWER": "dated"}]
        customer_break_date_pattern = [{"LOWER": {"IN":["customer","tenant"]}}, {"LOWER": "break"}, {"LOWER":"date", "OP":"?"}]
        
        
        # Add the patterns to the matcher
        self.matcher.add("RENT_VALUE", [rent_value_pattern])
        self.matcher.add("TERM", [term_pattern])
        self.matcher.add("COMMENCEMENT_DATE", [commencement_date_pattern])
        self.matcher.add("REVIEW_DATE", [review_date_pattern])
        self.matcher.add("LEASE_DATE", [lease_date_pattern])
        self.matcher.add("LEASE_DATE_2", [lease_date_pattern_2])
        self.matcher.add("CUSTOMER_BREAK_DATE", [customer_break_date_pattern])
        
        rent_after_pattern = rent_value_pattern +[
             {"OP": "*"},
             {"LOWER": {"IN": ["£", "$", "€"]}},
             {"TEXT": {"REGEX": r"[\d,.]+"}}]

        rent_before_pattern =[{"LOWER": {"IN": ["£", "$", "€"]}},
                     {"TEXT": {"REGEX": r"[\d,.]+"}},
                     {"OP": "*"}] + rent_value_pattern

        self.match_after.add("rent_after",[rent_after_pattern])
        self.match_before.add("rent_after",[rent_before_pattern])

        # works for x years, x (x) years... with spaces.
        term_length_pattern = [
            {"LIKE_NUM": True, "OP": "+"},
            {"IS_SPACE": True, "OP": "*"},
            {"IS_PUNCT": True, "OP":"?"},
            {"LIKE_NUM": True, "OP":"?"},
            {"IS_PUNCT": True, "OP":"?"},
            {"IS_SPACE": True, "OP": "*"},
            {"LOWER": {"IN": ["year", "years"]}}
        ]

        self.match_term.add("TERM_LENGTH", [term_length_pattern])

    def extract_info(self, text):
        doc = self.nlp(text)
        rent = None
        term_length = None
        commencement_date = None
        review_date = None
        lease_date = None
        customer_break_date = None
        
        matches = self.matcher(doc)

        # Extract and print the matched spans
        for match_id, start, end in matches:
            if self.nlp.vocab.strings[match_id] == "RENT_VALUE":
                if rent:
                    continue
                else:
                    rent = self.second_match(self.match_after, doc,start,min(end+200,len(doc)),r'[£$€][\d,.]+')
                    if rent:
                        continue
                    else:
                        rent = self.second_match(self.match_before, doc,max(start-15,0),end,r'[£$€][\d,.]+')
            elif self.nlp.vocab.strings[match_id] == "TERM":
                if term_length:
                    continue
                else:
                    span = doc[start: min(end+20,len(doc))]
                    matches_terms = self.match_term(span)
                    for term_id, start_t, end_t in matches_terms:
                        term_length = span[start_t:end_t].text

            elif self.nlp.vocab.strings[match_id] == "COMMENCEMENT_DATE":
#                 if doc[start-2: start-1].text.lower() in ["include", "including", "from", "to"] and doc[start-1: start].text.lower() in ["the"]:
#                     continue
#                 else:
                if commencement_date:
                    continue
                else:
                    commencement_date = self.extract_dates_with_sutime_and_dateparser(doc[start:end +25].text)
            
            elif self.nlp.vocab.strings[match_id] == "REVIEW_DATE":
                if review_date:
                    continue
                else:
#                     if doc[start+1: start+2] == "date(s":
#                         review_date = []
#                         review_date.append(self.extract_dates_with_sutime_and_dateparser(doc[start:end +50].text))
#                         review_date.append(self.extract_dates_with_sutime_and_dateparser(doc[start+10:end +50].text))
#                     else:
                        review_date = self.extract_dates_with_sutime_and_dateparser(doc[start:end +15].text)
                    
            elif self.nlp.vocab.strings[match_id] == "LEASE_DATE":
                if lease_date:
                    continue
                else:
                    lease_date = self.extract_dates_with_sutime_and_dateparser(doc[start-8:end +15].text)
                    
            elif self.nlp.vocab.strings[match_id] == "LEASE_DATE_2":
                if lease_date:
                    continue
                else:
                    lease_date = self.extract_dates_with_sutime_and_dateparser(doc[start:end +15].text)
                
            elif self.nlp.vocab.strings[match_id] == "CUSTOMER_BREAK_DATE":
                if customer_break_date:
                    continue
                else:
                    customer_break_date = self.extract_dates_with_sutime_and_dateparser(doc[start:end +15].text)


        self.info['Date of Lease'] = lease_date
        self.info['Annual Rent']= rent
        self.info['Term']= term_length
        self.info['Term Commencement Date'] = commencement_date
        self.info['Review Date'] = review_date
        self.info['Customer Break Date'] = customer_break_date
        
        return self.info

    
    def second_match(self, match_func, doc, start, end, reg_pattern):
        res = None
        span = doc[start: end]

        res_matched = match_func(span)
        if res_matched:
            res = re.search(reg_pattern, span.text).group()
        return res

    
    def extract_dates_with_sutime_and_dateparser(self, text):
#         self.nlp = stanza.Pipeline(processors='tokenize,ner', lang='en')
        processed_text = re.sub(r'(\d+)"', r'\1', text)
        doc = self.stanza_nlp(processed_text)
 
        dates = []
        for sentence in doc.sentences:
            for entity in sentence.ents:
                if entity.type == 'DATE':
                    if not any(indicator in entity.text.lower().split() for indicator in ["days", "date","day","year","years","month","months", "daily","bruntwood"]):
                        dates.append(entity.text)

        # If SUTime extracted any dates, return the first one
        if dates:
            dates = [date.replace("\n", " ") for date in dates]
            dates = self.filter_dates_with_datefinder(dates)
            if dates:
                return dates.strftime('%d-%m-%Y')


        datefinder_dates = list(datefinder.find_dates(text, strict = True))


        if datefinder_dates:
            return datefinder_dates[0].strftime('%d-%m-%Y')

        return None

    def filter_dates_with_datefinder(self, dates):
        for date_string in dates:
            parsed_dates = list(datefinder.find_dates(date_string))
            if parsed_dates:
                return parsed_dates[0]
        return None


# In[7]:


class ChooseFilePage(tk.Frame):
    def __init__(self, root, extractor):
        super().__init__(root)
        self.style = Style()
        self.style.theme_use('adapta')
        self.root = root
        self.extractor = extractor  # Store the RentExtractor instance
        self.pack(fill=tk.BOTH, expand=True)
        self.pack_propagate(False)

        self.file_label = tk.Label(self, text="  ", font=("Arial", 16))
        self.file_label.pack()
        
        self.logo = Image.open("Logo-bruntwood.png")
        self.logo = self.logo.resize((100, 50), Image.ANTIALIAS)
        self.tk_logo = ImageTk.PhotoImage(self.logo)
        
        # Create a Label widget for the image and place it using grid
        self.image_label = tk.Label(root, image=self.tk_logo)
        self.image_label.pack(anchor = "se")
#         self.image_label.pack(side = tk.TOP, padx=10, pady=10)  # Adjust padx, pady as needed

        self.choose_file = tk.Button(self, text="Choose File", width = 10,height = 3, command=self.open_file_dialog)
        self.choose_file.pack(pady=(50, 0), side = tk.LEFT, padx=10)

        self.extract_btn = tk.Button(self, text="Extract", width = 10,height =3, command=self.show_extracted_text)
        self.file_path = None

    def open_file_dialog(self):
        self.file_path = filedialog.askopenfilename()
        if self.file_path:
            self.file_label.config(text=f"File path: {self.file_path}", wraplength=self.winfo_width())
            messagebox.showinfo("Import file successfully!", f"{self.file_path} imported successfully!")
            self.extract_btn.pack(pady= (50,0), side = tk.LEFT, padx= 0)
        else:
            messagebox.showinfo("No file selected", "No file selected!")

    def show_extracted_text(self):
        threading.Thread(target=self.extract_text_display).start()


    def extract_text_display(self):
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Text Extraction Progress")
        progress_window.geometry("300x100")
        progress_window.resizable(False, False)

        progress_label = tk.Label(progress_window, text="Extracting text...", font=("Arial", 12))
        progress_label.pack(pady=10)

        self.progress_bar = Progressbar(progress_window, orient=tk.HORIZONTAL, length=200, mode='determinate')
        self.progress_bar.pack(pady=5)

        self.percentage_label = tk.Label(progress_window, text="0% extracted")
        self.percentage_label.pack(pady=5)

        extracted_text = self.extract_text_from_pdf(self.file_path)

        info = self.extractor.extract_info(extracted_text)

        progress_window.destroy()

        # Now, only pass the extracted rent to the DisplayTextPage
        DisplayTextPage(self.root, self.file_path, info, extracted_text)  # Pass extracted_text as well

        # Destroy the current page (ChooseFilePage)
        self.destroy()


    def extract_text_from_pdf(self, pdf_path):
        start = time.time()
        images = convert_from_path(pdf_path)
        text = ""
        total_images = len(images)

        for idx, image in enumerate(images, 1):

#             image.save('image.png')
#             text_list = image_to_text('image.png')
#             formatted_text = "\n".join([item[0] for item in text_list])
#             text+= formatted_text
#             os.remove('image.png')
            image_bytes = image.convert("RGB")
            text += pytesseract.image_to_string(image_bytes, lang='eng')


            # Update the progress bar with the percentage of extracted work
            percentage = (idx / total_images) * 100
            self.update_progress_bar(percentage)
            self.percentage_label.config(text=f"{int(percentage)}% extracted")
            self.progress_bar.update_idletasks()
        end = time.time()
        
        runtime = end - start
        print(runtime)
        
        return text

    def update_progress_bar(self, percentage):
        self.progress_bar["value"] = percentage
        self.root.update_idletasks()

            
    def setup_close_handler(self, text_extractor):
        # Register the cleanup function to be called when the program exits
        self.root.protocol("WM_DELETE_WINDOW", lambda: text_extractor.on_closing())
        


# In[8]:


class DisplayTextPage:
    def __init__(self, root, file_path, extracted_info, original_text):
        self.root = root
        self.root.title('Extracted Info')
        self.root.geometry('600x400')
        self.file_path = file_path 
        self.file_name = os.path.split(self.file_path)[-1]
        self.extractor = Extractor()

        file_label = tk.Label(self.root, text=f"File name: {self.file_name}", font=("Arial", 14), wraplength=580)
        file_label.pack(pady=10, padx=10, anchor=tk.W, fill=tk.X, expand=True)

        extracted_info_frame = tk.Frame(self.root)
        extracted_info_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("Key", "Value")
        self.treeview = ttk.Treeview(extracted_info_frame, columns=columns, show="headings", height=5)
        self.treeview.pack(fill=tk.BOTH, expand=True)

        self.treeview.heading("Key", text=" ")
        self.treeview.heading("Value", text="Value")

        for key, value in extracted_info.items():
            self.treeview.insert("", tk.END, values=(key, value))

        export_csv_btn = tk.Button(extracted_info_frame, text="Export CSV", command=self.export_to_csv)
        export_csv_btn.pack(pady=10, padx=10, side=tk.LEFT)

        export_txt_btn = tk.Button(extracted_info_frame, text="Export TXT", command=lambda: self.export_to_txt(original_text))
        export_txt_btn.pack(pady=10, padx=10, side=tk.LEFT)
        
        extract_next_btn = tk.Button(extracted_info_frame, text="Extract next file", command=self.go_to_choose_file)
        extract_next_btn.pack(pady=10, padx=10, side=tk.LEFT)
        
        
    def export_to_csv(self):
        origin_filename = os.path.split(self.file_path)[-1]

        # Get the user's chosen file path for saving CSV
        file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
        
        if file_path:
            filename = os.path.basename(file_path)

            with open(filename, mode="w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["Key", "Value"])  # Writing the header
                for item in self.treeview.get_children():
                    key = self.treeview.item(item, "values")[0]
                    value = self.treeview.item(item, "values")[1]
                    writer.writerow([key, value])

            tk.messagebox.showinfo("CSV Export", f"{origin_filename} data has been exported to {file_path}")


        
    def export_to_txt(self, original_text):
        origin_filename = os.path.split(self.file_path)[-1] 

        # Get the user's chosen file path
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
        
        if file_path:
            filename = os.path.basename(file_path)

            with open(file_path, 'w') as txt_file:
                txt_file.write(original_text)

            tk.messagebox.showinfo("TXT Export", f"{origin_filename} has been exported to {file_path}")
        
    def go_to_choose_file(self):
        # Destroy the current page (DisplayTextPage)
        self.root.destroy()

        # Recreate the ChooseFilePage
        self.root = ThemedTk(theme="adapta")  # Create a new root window
        app = TextExtractor(self.root)
        self.root.protocol("WM_DELETE_WINDOW", app.on_closing)
        self.root.mainloop()


# In[ ]:



if __name__ == "__main__":
    root = ThemedTk(theme="adapta")
    TextExtractor(root)
    root.mainloop()

