You will have to pip3 install the following:
```pip3 install rich```
```pip3 install cysystemd```
You will also have to give execution rights for both scripts
```chmod u+x epoch_stats.py```

For epoch_stats.py, if you'd like to see your pubkey along side your indices and have recently restarted your validator, you will need to run the script first with the ```--build-indicesdb``` flag as so:
```# ./epoch_stats.py --build-indicesdb```
and then you can continue running the script as you would

Both scripts contain a ``-h`` flag to show a meaningful help screen
