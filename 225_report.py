#!/usr/bin/python3 -u

from cysystemd.reader import JournalReader, JournalOpenMode, Rule
from datetime import datetime as dd

import time
import datetime
from datetime import timezone
import math

import re
import sys
import pickle
import os.path

from rich.console import Console
from rich.table import Table
from rich import box
from rich.table import Column

import argparse
import sys
import pickle
import os.path

def delta_epoch_type(x):
    x = int(x)
    if x < 3:
        raise argparse.ArgumentTypeError("Minimum delta epoch is 3, the default without any flags is 2 backwards")
    return x

parser=argparse.ArgumentParser(description='Generate a 225 report tool')
parser.add_argument('--service-name',type=str,nargs='?',default='validator.service',help='Service name for journalctl')
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('--today',action='store_true',default=False,help='Run once, only retriving today\'s numbers so far')
group.add_argument('--yesterday',action='store_true',default=False,help='Run once, only retriving yesterday\'s numbers so far')
group.add_argument('--xdays',default=-1,type=int,help='How many days into the past')
args = parser.parse_args()

genesis=datetime.datetime(2020,12,1,12,0,23,0,tzinfo=timezone.utc)

rules = (Rule("_SYSTEMD_UNIT", args.service_name))
reader = JournalReader()
reader.open(JournalOpenMode.LOCAL_ONLY)
reader.add_filter(rules)

attestations={}
voting={}
def get_voting(votemsg, desired_epochs):
    p=r'([a-zA-Z]+)\=([0-9\.a-z]+)'
    res=dict(re.findall(p,votemsg))
    if not int(res['epoch']) in desired_epochs:
        return

    pt = r'time\=\"([0-9\-\:\s]+)\"'
    t = list(re.findall(pt,votemsg))[0].split(' ')[1]
    res['time'] = t
    if res['pubKey'] in attestations:
      attestations[res['pubKey']].append(res['epoch'])
    else:
      attestations[res['pubKey']] = [res['epoch']]
    voting[f"{res['pubKey']}_{res['epoch']}"] = res

def get_225_data(end_epoch):
  desired_epochs = list(range(end_epoch-225,end_epoch))
  start_date = genesis + datetime.timedelta(0,desired_epochs[0]*384)
  start_at = start_date.timestamp() * 1000000
  print(f"Starting seek at {start_date} (epoch {desired_epochs[0]})...")
  reader.seek_realtime_usec(start_at)
  for record in reader:
      if not 'MESSAGE' in record.data.keys():
          continue

      msg=record.data['MESSAGE']
      if "Previous epoch voting summary" in msg:
          get_voting(msg, desired_epochs)

  wrong_head=0
  wrong_source=0
  wrong_target=0
  wrong_trifecta=0
  wrong_srctgt=0
  total_income=0
  total_loss=0
  print(f"Found {len(voting.keys())} items")
  print(f"Found {len(attestations.keys())} validators")
  min_epoch=999999
  max_epoch=0
  for pubkey, vd in voting.items():
      new_bal = "{:.9f}".format(float(vd['newBalance']))
      old_bal = "{:.9f}".format(float(vd['oldBalance']))
      new_bal = int("".join(new_bal.split('.')))
      old_bal = int("".join(old_bal.split('.')))
      delta = (new_bal-old_bal)
      total_income += delta

      if delta < 0:
          total_loss += delta

      if vd['correctlyVotedTarget'] != "true":
          wrong_target += 1
      if vd['correctlyVotedSource'] != "true":
          wrong_source += 1
      if vd['correctlyVotedHead'] != "true":
          wrong_head += 1
      if vd['correctlyVotedTarget'] != "true" and vd['correctlyVotedSource'] != "true" and vd['correctlyVotedHead'] != "true":
          wrong_trifecta += 1
      if vd['correctlyVotedTarget'] != "true" and vd['correctlyVotedSource'] != "true":
          wrong_srctgt += 1

      min_epoch=min(min_epoch,int(vd['epoch']))
      max_epoch=max(max_epoch,int(vd['epoch']))
  avg_attestations=0
  for pubkey, epochs_attested in attestations.items():
      avg_attestations += len(epochs_attested)
  avg_attestations = avg_attestations / len(attestations.keys())
  return {'avg_att': avg_attestations, 'min_epoch': min_epoch, 'max_epoch': max_epoch, 'total_income': total_income, 'total_loss': total_loss, 'head': wrong_head, 'target': wrong_target, 'source': wrong_source, 'trifecta': wrong_trifecta, 'srctgt': wrong_srctgt}

print("Welcome to 225 Report Generator")
now = datetime.datetime.utcnow()
if args.today:
      today_boundary=now.replace(hour=12,minute=0,second=23,microsecond=0,tzinfo=timezone.utc)
      today_boundary_epoch=math.floor((today_boundary-genesis).total_seconds()/384)
      end_of_today=today_boundary_epoch+225
      epoch=end_of_today
if args.yesterday:
      yesterday_boundary=now.replace(hour=12,minute=0,second=23,microsecond=0,tzinfo=timezone.utc)-datetime.timedelta(1)
      yesterday_boundary_epoch=math.floor((yesterday_boundary-genesis).total_seconds()/384)
      end_of_yesterday=yesterday_boundary_epoch+225
      epoch=end_of_yesterday
if args.xdays >0:
      yesterday_boundary=now.replace(hour=12,minute=0,second=23,microsecond=0,tzinfo=timezone.utc)-datetime.timedelta(args.xdays)
      yesterday_boundary_epoch=math.floor((yesterday_boundary-genesis).total_seconds()/384)
      end_of_yesterday=yesterday_boundary_epoch+225
      epoch=end_of_yesterday

data=get_225_data(epoch)
# Ascii print
table = Table(Column(header='data'), Column(header='val',justify='left'), title=":receipt: 225 Report", show_header=False, show_lines=True)
table.add_row("Epochs Covered",f"{data['min_epoch']}-{data['max_epoch']} ({data['max_epoch']-data['min_epoch']+1})")
table.add_row("Avg Att Per Epoch",f"{data['avg_att']:.2f}")
table.add_row("Total Att. Income",f"{data['total_income']} ({data['total_income']/10**9:.3f} ETH)")
table.add_row("Total Att. Loss",f"{data['total_loss']} ({data['total_loss']/10**9:.5f} ETH)")
table.add_row("Wrong Heads",f"{data['head']}")
table.add_row("Wrong Target",f"{data['target']}")
table.add_row("Wrong Source",f"{data['source']}")
table.add_row("Wrong hd+tgt+src",f"{data['trifecta']}")
table.add_row("Wrong hd+src",f"{data['srctgt']}")
table.box=box.ASCII

console = Console(color_system=None)
console.print(table)
