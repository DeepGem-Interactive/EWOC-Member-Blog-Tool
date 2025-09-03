from openai import AzureOpenAI
import os
import time
import requests
import tempfile
from dotenv import load_dotenv
load_dotenv()

class AzureServices:
    def __init__(self):
        self.text_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-02-15-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
        
        self.conversations = {}

    def rewrite_content(self, original_text, tone, tone_description, keywords, firm_name, location, lawyer_name, city, state, planning_session_name="15-minute discovery call", discovery_call_link=""):
        response = self.text_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": f"""
                    You are a legal blog post rewriter. There should be At least 30% changes from original. Rewrite the article following these strict guidelines:
                    SEO REQUIREMENTS:
                    1. Must include these elements within the first 150 words:
                       - Primary keywords: {keywords}
                       - Firm name: {firm_name}
                       - City-state of firm: {location}
                       - Lawyer name: {lawyer_name}
                       - City-state of Lawyer: {city}, {state}
                    2. Incorporate naturally - don't just list them
                    
                    TONE REQUIREMENTS:
                    1. Primary Tone: {tone}
                    2. Tone Description: {tone_description}
                    3. Consistency: Maintain this tone throughout the entire article
                    
                    SPECIAL BRANDING REQUIREMENTS:
                    - Avoid transactional language like "investing in" which are not aligned with the Personal Family Lawyer® brand tone
                    - Instead use phrases like:
                        * "work with us to choose a plan that works to keep your loved ones out of court and out of conflict"
                        * "create a plan that protects what matters most"
                        * "develop a comprehensive approach to safeguarding your family's future"
                        * "put a plan in place that ensures your wishes are honored"
                        * "create a plan that grows with your family and ensures lasting peace of mind"
                    - Emphasize the ongoing relationship and family protection aspects rather than transactional terms
                    - Use the term "{planning_session_name}" when referencing to planning sessions.

                    CONTENT GUIDELINES:
                    DO's:
                    1. Use active voice
                    2. Structure with 5 sections: introduction, 3 subheadings, and conclusion with call-to-action
                    3. Keep length between 1000-1200 words
                    4. Use transition sentences between sections
                    5. Conclusion should be brief (1-2 sentences) with clear call-to-action
                    6. Include 1-2 bulleted lists in the entire article
                    7. Balance paragraphs and lists appropriately
                    8. Write in a {tone} tone
                    9. Include these keywords naturally: {keywords}
                    10. Mention {firm_name} in {location} where relevant
                    11. Firm name is {firm_name} and location is {location}
                    12 Lawyer name is {lawyer_name} and location is {city}, {state}
                    
                    DON'Ts:
                    1. Avoid legal jargon or complex language (keep it high-school level)
                    2. No passive voice
                    3. Don't use lists without context
                    4. Limit metaphors
                    5. Don't make conclusion too long
                    6. Don't include more than 5 sources
                    7. Don't exceed 1200 words
                    8. Don't use more than 3 lists
                    
                    CTA REQUIREMENTS:
                    1. MUST use the exact phrase "15-minute Discovery Call" (never "consultation" or "consult")
                    2. Standard format: "Schedule your complimentary 15-minute Discovery Call with {firm_name} today"
                    3. Include a clear call-to-action like "Click here to schedule" or "Book your Discovery Call now"
                    4. Never offer to answer questions or provide consultation during this call
                    5. Use the discovery call link: {discovery_call_link} when creating hyperlinks

                    STYLE GUIDE UPDATES:
                    1. LANGUAGE PREFERENCE:
                    - Use "loved ones" instead of "family" in all cases EXCEPT when:
                        * Referring specifically to legal family members (spouse, children, parents)
                        * Discussing family law matters specifically related to spouse, children, parents
                        * The context explicitly requires "family" (e.g., "family business")
                    - Preferred phrases:
                        * "protect your loved ones"
                        * "ensure your loved ones are cared for"
                        * "keep your loved ones out of court"
                        * "provide for your loved ones"

                    Formatting Requirements:
                    # Main Title
                    ## Subheading 1
                    ### Sub-subheading (if needed)
                    **Bold important terms**
                    - Bullet points when appropriate
                    [Link text](URL) for references
                    
                    The article must be valuable, engaging, and optimized for both readers and search engines.
                """},
                {"role": "user", "content": original_text}
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content

    def edit_content(self, session_id, user_message, current_content=None):
        if session_id not in self.conversations:
            self.conversations[session_id] = [
                {"role": "system", "content": """
                    You are a legal blog post editor. When the user requests changes:
                    1. Make ONLY the requested changes
                    2. Return the COMPLETE updated blog (not just updated part) in markdown format
                    3. Don't include any commentary or explanations
                    4. Preserve all formatting and structure
                """}
            ]
        
        if current_content:
            self.conversations[session_id].append(
                {"role": "assistant", "content": current_content}
            )
        
        self.conversations[session_id].append(
            {"role": "user", "content": user_message}
        )
        
        response = self.text_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=self.conversations[session_id],
            temperature=0.5
        )
        
        ai_response = response.choices[0].message.content
        self.conversations[session_id].append(
            {"role": "assistant", "content": ai_response}
        )
        
        return ai_response
    
class ImageGenerator:
    def __init__(self):
        self.image_client = AzureOpenAI(
            api_key=os.getenv("AZURE_DALLE_KEY"),
            api_version="2024-02-01",
            azure_endpoint=os.getenv("AZURE_DALLE_ENDPOINT")
        )
        self.text_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-02-15-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
  
    def generate_image(self, text_prompt):
        try:
            safe_prompt = self._get_safe_image_prompt(text_prompt)
            
            response = self.image_client.images.generate(
                model=os.getenv("AZURE_DALLE_DEPLOYMENT"),
                prompt=safe_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            
            # Create 'generated' directory if it doesn't exist
            generated_dir = os.path.join(tempfile.gettempdir(), 'generated')
            os.makedirs(generated_dir, exist_ok=True)
            
            timestamp = int(time.time())
            image_filename = f"image_{timestamp}.png"
            image_path = os.path.join(generated_dir, image_filename)
            
            # Download and save the image
            response = requests.get(image_url)
            with open(image_path, 'wb') as f:
                f.write(response.content)
            
            return image_filename
            
        except Exception as e:
            print(f"Image generation failed: {e}")
            return None

    def _get_safe_image_prompt(self, text_prompt):
        response = self.text_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": """
                    You are a creative prompt engineer for legal blog images. Create safe and professional image prompts that:
                    1. Are directly relevant to the blog content
                    2. Be 'unique to the blog's content', not generic or reusable for any legal article
                    3. Reflect the main topic, themes, or message of the blog post
                    4. Focus on modern, visually appealing representations
                    5. Must pass Azure content filters
                    6. Avoids sensitive content
                    The prompt should be detailed and specific, including:
                        - Main subject
                        - Style description
                        - Color palette
                        - Composition notes
                        - Mood/tone
                    - Is based on this blog content:
                """},
                {"role": "user", "content": text_prompt[:1000]}
            ],
            temperature=1
        )
        return response.choices[0].message.content


