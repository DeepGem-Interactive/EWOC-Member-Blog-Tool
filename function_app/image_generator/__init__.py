import azure.functions as func
import logging
import json
from shared.azure_services import ImageGenerator
import base64
import os
import tempfile

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    image_generator = ImageGenerator()
    try:
        req_body = req.get_json()
        text_prompt = req_body.get('text_prompt')
        
        # Generate image
        image_filename = image_generator.generate_image(text_prompt)
        
        if not image_filename:
            raise ValueError("Image generation failed")

        # Read the image file
        generated_dir = os.path.join(tempfile.gettempdir(), 'generated')
        image_path = os.path.join(generated_dir, image_filename)
        with open(image_path, 'rb') as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')

        # Log successful invocation for monitoring
        logging.info(f"Image generator function completed successfully. Image filename: {image_filename}")
        logging.info(f"Function invocation parameters - Text prompt length: {len(text_prompt)}")

        return func.HttpResponse(
            json.dumps({
                "image_filename": image_filename,
                "image_data": image_data
            }),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Error in image generation: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )
