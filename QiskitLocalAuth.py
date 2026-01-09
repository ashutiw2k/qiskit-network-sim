# Load the API key from the JSON file
import json
with open('secrets/keys.json') as f:
    keys = json.load(f)
my_api_key = keys["qiksit-api-key"]
my_crn_instance = keys["qiskit-crn-instance"]

from qiskit_ibm_runtime import QiskitRuntimeService
 
QiskitRuntimeService.save_account(
token=my_api_key, # Use the 44-character API_KEY you created and saved from the IBM Quantum Platform Home dashboard
instance=my_crn_instance, # Optional
)

