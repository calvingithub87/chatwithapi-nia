import os
from fastapi import UploadFile, HTTPException
from data.GPTData import GPTData
import logging
import json
import re
import tiktoken

from mongo_service import update_usecases, update_orders

logger = logging.getLogger(__name__)

delimiter = "```"
UPLOAD_FOLDER = "uploads"
APP_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, "appimages")
CHAT_IMAGES_FOLDER = os.path.join(UPLOAD_FOLDER, "chatimages")
RAG_DOCUMENTS_FOLDER = os.path.join(UPLOAD_FOLDER, "ragdocuments")

token_encoder = tiktoken.encoding_for_model("gpt-4o")

def create_folders():
    # Create upload folders if they don't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(APP_IMAGES_FOLDER, exist_ok=True)
    os.makedirs(RAG_DOCUMENTS_FOLDER, exist_ok=True)
    os.makedirs(CHAT_IMAGES_FOLDER, exist_ok=True)

def create_app_directories():
    # Create the folders for file upload
    STATIC_RESOURCES_FOLDER = "static"
    STATIC_IMAGES_FOLDER = os.path.join(STATIC_RESOURCES_FOLDER, "images")
    STATIC_SCRIPTS_FOLDER = os.path.join(STATIC_RESOURCES_FOLDER, "js")
    STATIC_CSS_FOLDER = os.path.join(STATIC_RESOURCES_FOLDER, "css")

    # Create upload folders if they don't exist
    os.makedirs(STATIC_RESOURCES_FOLDER, exist_ok=True)
    os.makedirs(STATIC_IMAGES_FOLDER, exist_ok=True)
    os.makedirs(STATIC_SCRIPTS_FOLDER, exist_ok=True)
    os.makedirs(STATIC_CSS_FOLDER, exist_ok=True)

async def handle_upload_files(gpt: GPTData, files: list[UploadFile]):
    # Additional validation (you can add more checks here, like file type validation)
    if gpt.use_rag:
        total_size = sum(file.size for file in files)
        if total_size > 10 * 1024 * 1024:  # 10 MB limit
            raise HTTPException(status_code=400, detail="Total file size exceeds 10MB limit.")
        
    logger.info(f"Use Rag : {gpt.use_rag}")

    file_upload_status = ""

    for uploadedFile in files:
        file_extension = os.path.splitext(uploadedFile.filename)[1].lower()
        file_name = os.path.splitext(uploadedFile.filename)[0]

        print(f"file_extension : {file_extension}")
        logger.info(f"file_extension : {file_extension}")

        if gpt.use_rag and file_extension in ('.png', '.jpg', '.jpeg'):
            file_path = os.path.join(APP_IMAGES_FOLDER, uploadedFile.filename) 
        elif gpt.use_rag and file_extension in ('.json', '.jsonl', '.pdf', '.csv', '.txt'):
            file_path = os.path.join(RAG_DOCUMENTS_FOLDER, uploadedFile.filename)
            try:
                with open(file_path, "wb") as buffer:
                    content = uploadedFile.file.read()
                    if content:
                        buffer.write(content)
                    else:
                        raise HTTPException(status_code=500, detail="Error saving file: Empty file.")
                
                if file_name == 'usecases':
                    try:
                        with open(file_path, "r", encoding='utf-8') as json_file:
                            usecases = json.load(json_file)
                            # Assuming gpt_id is available in the gpt object
                            # for usecase in usecases:
                            #     usecase['gpt_id'] = gpt.gpt_id
                            await update_usecases(usecases)
                            file_upload_status += f"File {uploadedFile.filename} processed and database updated successfully."
                    except Exception as e:
                        file_upload_status += f"Error processing file: {str(e)}"
                        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
                elif 'Order' in file_name:
                    try:
                        with open(file_path, "r", encoding='utf-8') as json_file:
                            orders = [json.loads(line) for line in json_file]
                            await update_orders(orders)
                            file_upload_status += f"File {uploadedFile.filename} processed and database updated successfully."
                    except Exception as e:
                        file_upload_status += f"Error processing file: {str(e)}"
                        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")
                
                file_upload_status += f"File {uploadedFile.filename} saved successfully."
            except Exception as e:
                file_upload_status += f"Error saving file: {str(e)}"
                raise HTTPException(status_code=500, detail=f"Error saving file: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail="Invalid file type for RAG usage.")

    return file_upload_status

def handle_image_uploads(uploadedFile: UploadFile):
    file_size = uploadedFile.size
    file_upload_status = ""

    if file_size > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=400, detail="Total file size exceeds 10MB limit.")
    
    file_extension = os.path.splitext(uploadedFile.filename)[1].lower()

    if file_extension in ('.png', '.jpg', '.jpeg'):
        file_path = os.path.join(CHAT_IMAGES_FOLDER, uploadedFile.filename) 
        
        try:
            with open(file_path, "wb") as buffer:
                content = buffer.write(uploadedFile.file.read())
                file_upload_status += f"Image {uploadedFile.filename} saved successfully."
        except Exception as e:
            file_upload_status += f"Error saving file: {str(e)}"
            raise HTTPException(status_code=500, detail=f"Error saving file: {str(e)}")
        
    return file_path

"""
Response from model will be wrapped within json```\n{...}\n``` block. This function extracts the json content from the response.

This uses a regular expression to match the content inside the Markdown code block (json syntax) and captures everything between json\n` and `\n.
The r'\1' part replaces the whole match with the content inside the captured group, effectively removing the Markdown code block formatting.
The flags=re.DOTALL argument allows the dot (.) in the regex to match newline characters, ensuring that the entire content inside the code block is captured, even if it spans multiple lines.
"""
def extract_response(response):
    extracted_text = ""

    try:
        if response.find('```json\n') != -1:
            json_pattern = r'```json\n(.*?)\n```'
        elif response.find('```\n') != -1:
            json_pattern = r'```\n(.*?)\n```'
            
        extracted_text = re.sub(json_pattern, r'\1', response, flags=re.DOTALL).strip()
    except Exception as e:
        if response.find('### Response') != -1:
            extracted_text = response.split('### Response')[1].strip()
        else:
            extracted_text = extract_response_via_delimiter(response, "{", "}")

    logger.info(f"Extracted Text: {extracted_text}")

    return parse_json(extracted_text)

def extract_response_via_delimiter(response, start, end):
    extracted_text = ""

    start_index = response.find(start)
    end_index = response.rfind(end) + 1
    extracted_text = response[start_index:end_index].strip()

    return extracted_text

def parse_json(extracted_text):
    return json.loads(extracted_text)

# data = """{\n    "model_response": "Here are the details of order OR00147: The requested information is not available in the retrieved data. Please try another query or topic.",\n    "follow_up_questions": [\n        "Can you provide any additional information about the order?",\n        "Do you have any other order numbers that I can help you with?",\n        "Is there anything else I can assist you with?"\n    ]\n}"""
# print(parse_json(data))

def get_previous_context_conversations(conversation_list, previous_conversations_count):
    """
    Fetches the last 'n' conversations from a conversation list.

    Args:
        conversation_list: A list of conversations.  Each conversation 
                          can be represented as a dictionary, string, or any other suitable data type.
        n: The number of last conversations to fetch. Defaults to 4.

    Returns:
        A list containing the last 'n' conversations. 
        Returns an empty list if the conversation_list is empty or n is 0.
        If n is larger than the conversation list's length, it returns the entire list.
    """

    if not conversation_list or previous_conversations_count == 0:
        return []

    previous_conversations = []
    for conversation in conversation_list[-previous_conversations_count:]:  # Use slicing to efficiently get the last n elements
        if conversation["role"] == "system":
            pass
        else:
            previous_conversations.append(conversation)
        
    logger.info(f"previous_conversations {previous_conversations}")

    return previous_conversations

def trim_conversation_history(conversation_history, max_tokens):
    total_tokens = sum(len(msg['content'].split()) for msg in conversation_history)  # Simple token count (by word)
    
    while total_tokens > max_tokens:
        # Remove the earliest user-assistant pairs to make space
        conversation_history.pop(1)  # Remove the first user message (system message stays)
        conversation_history.pop(1)  # Remove the first assistant message
        total_tokens = sum(len(msg['content'].split()) for msg in conversation_history)
    
    return conversation_history

async def extract_json_content(response):
    total_tokens = response.usage.total_tokens
    main_response = response.choices[0].message.content
    follow_up_questions=[]

    # Find content between json``` and ```
    json_match = re.search(r'```json\n(.*?)```', main_response, re.DOTALL)
    
    if json_match:
        try:
            # Parse the extracted content as JSON
            follow_up_questions = json.loads(json_match.group(1).strip())
            follow_up_questions = follow_up_questions["follow_up_questions"]

             # Remove the entire JSON block from main_response
            main_response = main_response.replace(json_match.group(0), '').strip()
        except json.JSONDecodeError as je:
            logger.info(f"exception occurred while json pattern selected {str(je)}")

    return main_response, follow_up_questions, total_tokens 

# Token counting function
async def count_tokens(text: str, model_name: str) -> int:
    tokens = 0
    try:
        #tokenizer = MODEL_TOKENIZERS.get(model_name)
        if model_name == "gpt-4o" or model_name == "gpt-3.5":
            tokens = len(token_encoder.encode(str(text)))  # OpenAI's `tiktoken`
    except Exception as e:
        logger.error(f"Tokenization error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tokenization error: {str(e)}")
    finally:
        logger.info(f"Token count {tokens} for model {model_name}")
    
    return tokens


async def get_token_count(model_name, system_message,  conversations, user_message, max_tokens):
    # Construct the token request
    # Remove the system message from the conversation history
    user_conversations: str = ""
    for msg in conversations:
        if msg["role"] != "system":
            user_conversations += msg["content"] + " "

    # Calculate tokens for each component
    system_tokens = await count_tokens(system_message, model_name)
    history_tokens = await count_tokens(user_conversations, model_name)
    query_tokens = await count_tokens(user_message, model_name)

    logger.info(f"System Tokens: {system_tokens}, History Tokens: {history_tokens}, Query Tokens: {query_tokens}")

    # Total estimated tokens
    estimated_tokens = system_tokens + history_tokens + query_tokens + max_tokens

    return {"token_breakdown": 
                {
                    "message_history": history_tokens,
                    "user_query": query_tokens,
                    "system_message": system_tokens,
                    "max_response": max_tokens,
                    "estimated_max_tokens": estimated_tokens
                }
            }