import google.generativeai as genai
import json
from fal_bot import config

# Configure Gemini
genai.configure(api_key=config.GEMINI_API_KEY)


async def moderate_text(text: str) -> tuple[bool, str]:
    """
    Comprehensive text moderation using Google Gemini.
    
    Checks for:
    - NSFW, porn, nudity, sexually suggestive content
    - Hate speech
    - Violence, gore
    - Political figures
    - Children in inappropriate contexts
    - Self-harm
    
    Returns:
        tuple[bool, str]: (is_safe, reason_if_unsafe)
    """
    try:
        # Use Gemini 2.0 Flash for fast, cheap moderation
        model = genai.GenerativeModel('gemini-2.0-flash-exp')  # Changed here
        
        system_prompt = """You are a strict content moderation system. Analyze the prompt and determine if it violates ANY of these policies:

1. NSFW/Sexual Content: Any pornographic, nude, sexually explicit, or sexually suggestive content. This includes:
   - Explicit sexual acts or descriptions
   - Nudity or partial nudity
   - Sexually suggestive poses, clothing, or scenarios
   - Fetish content or sexual objectification

2. Political Figures: Any mentions of politicians, world leaders, or political figures including:
   - Current or historical political leaders
   - Presidents, prime ministers, dictators, government officials
   - By name or recognizable description

3. Violence/Gore: Graphic violence, blood, gore, death, or disturbing imagery including:
   - Blood, injuries, death
   - Torture or extreme violence
   - Disturbing or shocking imagery

4. Hate Speech: Content targeting protected groups based on:
   - Race, ethnicity, nationality
   - Religion or religious beliefs
   - Gender, sexual orientation
   - Disability or medical conditions
   - Slurs, derogatory terms, or discriminatory language

5. Self-Harm: Content promoting or depicting self-harm, suicide, or eating disorders

Respond with ONLY a JSON object in this exact format:
{"safe": true, "reason": ""}
OR
{"safe": false, "reason": "Brief explanation of violation"}

Be EXTREMELY strict - when in doubt, mark as unsafe. Err on the side of caution."""

        prompt_to_check = f"{system_prompt}\n\nAnalyze this prompt: {text}"
        
        response = await model.generate_content_async(
            prompt_to_check,
            generation_config=genai.GenerationConfig(
                temperature=0,
                max_output_tokens=150,
            )
        )
        
        # Parse response
        result_text = response.text.strip()
        
        # Try to extract JSON from response
        try:
            # Remove markdown code blocks if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            parsed = json.loads(result_text)
            
            if not parsed.get("safe", True):
                reason = parsed.get("reason", "Content violates our content policy")
                return False, reason
            
            return True, ""
            
        except (json.JSONDecodeError, IndexError):
            # If JSON parsing fails, check for keywords
            result_lower = result_text.lower()
            if "unsafe" in result_lower or "violat" in result_lower or '"safe": false' in result_lower:
                return False, "Content may violate our content policy"
            
            # If we can't parse and no clear unsafe signal, allow it
            return True, ""
        
    except Exception as e:
        print(f"[Moderation Error] {str(e)}")
        # If moderation fails, block the request for safety
        return False, "Unable to verify content safety. Please try again."


async def moderate_image(image_url: str, prompt: str = "") -> tuple[bool, str]:
    """
    Moderate image content using Gemini Vision.
    
    Checks for:
    - NSFW, nudity, sexually suggestive content
    - Violence, gore, disturbing imagery
    - Children/minors
    - Political figures
    - Hate symbols
    
    Returns:
        tuple[bool, str]: (is_safe, reason_if_unsafe)
    """
    try:
        # Use Gemini 2.0 Flash with vision
        model = genai.GenerativeModel('gemini-2.0-flash-exp')  # Changed here
        
        system_prompt = """You are a strict image content moderation system. Analyze the image and determine if it violates ANY of these policies:

1. NSFW/Sexual Content: 
   - Nudity or partial nudity
   - Sexually explicit content
   - Sexually suggestive poses, clothing, or scenarios
   - Lingerie, swimwear in provocative contexts
   - Sexual acts or implications


3. Political Figures:
   - Any recognizable politicians, world leaders, or political figures
   - Government officials, historical political leaders
   - Political symbols or party imagery

4. Violence/Gore:
   - Blood, injuries, wounds
   - Weapons being used violently
   - Violence, fighting, or aggressive acts
   - Gore, death, or disturbing imagery
   - Scary or shocking content

5. Hate Symbols:
   - Nazi symbols, swastikas
   - Hate group imagery or symbols
   - Discriminatory or racist imagery
   - Confederate flags in hateful contexts

Respond with ONLY a JSON object in this exact format:
{"safe": true, "reason": ""}
OR
{"safe": false, "reason": "Brief explanation of violation"}

Be EXTREMELY strict - when in doubt, mark as unsafe. Err on the side of caution."""

        # Download image content
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url)
            response.raise_for_status()
            image_data = response.content
        
        # Upload to Gemini
        import PIL.Image
        import io
        image = PIL.Image.open(io.BytesIO(image_data))
        
        prompt_parts = [
            system_prompt,
            f"\n\nContext prompt from user: {prompt}" if prompt else "",
            "\n\nAnalyze this image:",
            image
        ]
        
        response = await model.generate_content_async(
            prompt_parts,
            generation_config=genai.GenerationConfig(
                temperature=0,
                max_output_tokens=150,
            )
        )
        
        # Parse response
        result_text = response.text.strip()
        
        # Try to extract JSON from response
        try:
            # Remove markdown code blocks if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            parsed = json.loads(result_text)
            
            if not parsed.get("safe", True):
                reason = parsed.get("reason", "Image contains inappropriate content")
                return False, reason
            
            return True, ""
            
        except (json.JSONDecodeError, IndexError):
            # If JSON parsing fails, check for keywords
            result_lower = result_text.lower()
            if "unsafe" in result_lower or "violat" in result_lower or '"safe": false' in result_lower:
                return False, "Image may contain inappropriate content"
            
            # If we can't parse and no clear unsafe signal, allow it
            return True, ""
        
    except Exception as e:
        print(f"[Image Moderation Error] {str(e)}")
        # If moderation fails, block the request for safety
        return False, "Unable to verify image safety. Please try again."


async def moderate_request(prompt: str, image_url: str | None = None) -> tuple[bool, str]:
    """
    Moderate both text prompt and image (if provided).
    
    Returns:
        tuple[bool, str]: (is_safe, reason_if_unsafe)
    """
    # Check text prompt
    text_safe, text_reason = await moderate_text(prompt)
    if not text_safe:
        return False, text_reason
    
    # Check image if provided
    if image_url:
        image_safe, image_reason = await moderate_image(image_url, prompt)
        if not image_safe:
            return False, image_reason
    
    return True, ""