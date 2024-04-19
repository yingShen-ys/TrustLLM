import os, json
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
import google.generativeai as genai
from google.generativeai.types import safety_types
from fastchat.model import load_model, get_conversation_template
from openai import OpenAI,AzureOpenAI
from tenacity import retry, wait_random_exponential, stop_after_attempt
import requests
from trustllm.utils import file_process
import trustllm
import trustllm.config
import replicate

# online_model = trustllm.config.model_info['online_model']
# deepinfra_model = trustllm.config.model_info['deepinfra_model']

model_info = trustllm.config.model_info
online_model_list = model_info['online_model']
model_mapping = model_info['model_mapping']
rev_model_mapping = {value: key for key, value in model_mapping.items()}

safety_setting = [
            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_DEROGATORY,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },

            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_VIOLENCE,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },

            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_SEXUAL,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },

            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_TOXICITY,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_MEDICAL,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": safety_types.HarmCategory.HARM_CATEGORY_DANGEROUS,
                "threshold": safety_types.HarmBlockThreshold.BLOCK_NONE,
            },
        ]


def get_models():
    return model_mapping, online_model_list

def get_access_token():
    url = "https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={}&client_secret=".format(
        trustllm.config.client_id,
        trustllm.config.client_secret
    )

    payload = json.dumps("")
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    return response.json().get("access_token")


def get_ernie_res(string, temperature):
    if (temperature == 0.0):
        temperature = 0.00000001
    url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token=" + get_access_token()
    payload = json.dumps({
        "messages": [
            {
                "role": "user",
                "content": string,
            }
        ],
        'temperature': temperature
    })
    headers = {
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    print(response.text)
    res_data = json.loads(response.text)
    result_text = res_data.get('result', '')
    return result_text



def get_res_openai(string, model, temperature):
    gpt_model_mapping={ "chatgpt":"gpt-3.5-turbo",
        "gpt-4":"gpt-4-1106-preview"}
    
    gpt_model=gpt_model_mapping[model]
    api_key = trustllm.config.openai_key
    client = OpenAI(api_key=api_key,)
    stream = client.chat.completions.create(model=gpt_model,
                                            messages=[{"role": "user", "content": string}],
temperature=temperature,)
    if not stream.choices[0].message.content:
        raise ValueError("The response from the API is NULL or an empty string!")
    response = stream.choices[0].message.content
    return response



def deepinfra_api(string, model, temperature):
    api_token = trustllm.config.deepinfra_api
    top_p = 1 if temperature <= 1e-5 else 0.9
    OpenAI(api_key=api_token,api_base="https://api.deepinfra.com/v1/openai")
    stream = client.chat.completions.create(
        model=rev_model_mapping[model],
        messages=[{"role": "user", "content": string}],
        max_tokens=5192,
        temperature=temperature,
        top_p=top_p,)
    response = stream.choices[0].message.content
    return response



def replicate_api(string, model, temperature):
    input={"prompt": string, "temperature": temperature}
    if model in ["llama3-70b","llama3-8b"]:
        input["prompt_template"] = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nYou are a helpful assistant<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    else:
        input["prompt"]=prompt2conversation(rev_model_mapping[model],string)
    os.environ["REPLICATE_API_TOKEN"] = trustllm.config.replicate_api
    res = replicate.run(rev_model_mapping[model],
        input=input
    )
    res = "".join(res)
    return res


@retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(6))
def claude_api(string, model, temperature):
    anthropic = Anthropic(
        # defaults to os.environ.get("ANTHROPIC_API_KEY")
        api_key=trustllm.config.claude_api,
    )

    completion = anthropic.completions.create(
        model=model,  # "claude-2", "claude-instant-1"
        max_tokens_to_sample=4000,
        temperature=temperature,
        prompt=f"{HUMAN_PROMPT} {string}{AI_PROMPT}", )

    # print(chat_completion.choices[0].message.content)
    return completion.completion


@retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(6))
def gemini_api(string, temperature):
    genai.configure(api_key=trustllm.config.gemini_api)
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(string, temperature=temperature, safety_settings=safety_setting)
    return response



@retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(6))
def palm_api(string, model, temperature):
    genai.configure(api_key=trustllm.config.palm_api)

    model_mapping = {
        'bison-001': 'models/text-bison-001',
    }
    completion = genai.generate_text(
        model=model_mapping[model],  # models/text-bison-001
        prompt=string,
        temperature=temperature,
        # The maximum length of the response
        max_output_tokens=4000,
        safety_settings=safety_setting
    )
    return completion.result


@retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(6))
def zhipu_api(string, model, temperature):
    from zhipuai import ZhipuAI
    client = ZhipuAI(api_key=trustllm.config.zhipu_api)
    if temperature == 0:
        temperature = 0.01
    else:
        temperature = 0.99
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": string},
        ],
        temperature=temperature
    )
    print(response.choices[0].message.content)
    return response.choices[0].message.content


@retry(wait=wait_random_exponential(min=1, max=10), stop=stop_after_attempt(5))
def gen_online(model_name, prompt, temperature, replicate=False, deepinfra=False):
    if model_name in model_info['wenxin_model']:
        res = get_ernie_res(prompt, temperature=temperature)
    elif model_name in model_info['google_model']:
        if model_name == 'bison-001':
            res = palm_api(prompt, model=model_name, temperature=temperature)
        elif model_name == 'gemini-pro':
            res = gemini_api(prompt, temperature=temperature)
    elif model_name in model_info['openai_model']:
        res = get_res_openai(prompt, model=model_name, temperature=temperature)
    elif model_name in model_info['deepinfra_model']:
        res = deepinfra_api(prompt, model=model_name, temperature=temperature)
    elif model_name in model_info['claude_model']:
        res = claude_api(prompt, model=model_name, temperature=temperature)
    elif model_name in model_info['zhipu_model']:
        res = zhipu_api(prompt, model=model_name, temperature=temperature)
    elif replicate:
        res = replicate_api(prompt, model_name, temperature)
    elif deepinfra:
        res = deepinfra_api(prompt, model_name, temperature)
    else:
        raise ValueError(f"Unknown model name: {model_name}")
    return res


def prompt2conversation(model_path,prompt):
    msg = prompt
    conv = get_conversation_template(model_path)
    conv.set_system_message('')
    conv.append_message(conv.roles[0], msg)
    conv.append_message(conv.roles[1], None)
    conversation = conv.get_prompt()
    return conversation