## Ideation

Use binance api to collect bitcoin data
=> http
=> socket connection

can also get information on sbe (binary data) instead of json for faster speed

We can also think when the websocket gets disconnected (In this case we should use previous value, or at least think of a way to not break the service)

USE SBE data stream to send real-time? prediction on the server
=> so if it is predicted to go up (buy)
=> vice versa sell

Also use rest api to gather old data..!

stack all data on the s3 than move to the rdms and nosql
Use s3 to store the whole data 
and gonna transform the data and move to rdms
gona use nosql like redis or dynamo db as cache for inference.

So how im gonna use the data
when we ingest the data we are going use sbe stream to use directly for inference.
We also the data will go to the lake and be transformed to be saved in rdms
the data on rdms will also be used to train the model
and make a mlops cycle

most of the product will be run on the aws 
also trying to monitor the log and save it and also take control of the workflow orchestration for automization

i want to run inference ml in real-time (making the inference time bounded)
Also will run llm in a distributed manner to explain the data
In addition visualization of the data will also be provided to the user