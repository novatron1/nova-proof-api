"""Optional HTTP model connector. Endpoint/schema must be verified against the user's provider."""
import json,os,urllib.request,urllib.error
class MetaModelClient:
    def __init__(self,base_url=None,model=None,api_key=None,timeout=25):
        self.base_url=base_url or os.getenv('NOVA_MODEL_ENDPOINT')
        self.model=model or os.getenv('NOVA_MODEL_ID')
        self.api_key=api_key or os.getenv('NOVA_MODEL_API_KEY')
        self.timeout=timeout
        if not self.base_url or not self.model:raise ValueError('Set NOVA_MODEL_ENDPOINT and NOVA_MODEL_ID')
        if not self.base_url.startswith('https://') and not self.base_url.startswith('http://127.0.0.1:'):
            raise ValueError('Model endpoint must use HTTPS (except local loopback)')
    def __call__(self,prompt):
        # OpenAI-compatible chat completions transport, not a claim of Meta-native compatibility.
        data=json.dumps({'model':self.model,'messages':[{'role':'user','content':prompt}],'temperature':0}).encode()
        headers={'Content-Type':'application/json'}
        if self.api_key:headers['Authorization']='Bearer '+self.api_key
        req=urllib.request.Request(self.base_url,data=data,headers=headers,method='POST')
        with urllib.request.urlopen(req,timeout=self.timeout) as response:
            payload=json.load(response)
        return payload['choices'][0]['message']['content']
