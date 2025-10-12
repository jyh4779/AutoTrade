import os, json
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def llm_adjust_and_explain(payload, base_score, system_prompt, rubric, out_schema):
    messages = [
        {"role":"system","content": system_prompt + "\n\n[루브릭]\n" + rubric + "\n\n출력은 반드시 유효 JSON만"},
        {"role":"user","content": json.dumps({"base_score": base_score, "snapshot": payload}, ensure_ascii=False)}
    ]
    resp = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.1, messages=messages,
        response_format={ "type":"json_object" }
    )
    return json.loads(resp.choices[0].message.content)
