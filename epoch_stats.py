#!/usr/bin/python3

from cysystemd.reader import JournalReader, JournalOpenMode, Rule
from datetime import datetime as dd

import time
import datetime
from datetime import timezone
import math

from rich.console import Console
from rich.table import Table
from rich import box
from rich.table import Column
import re
import argparse
import sys
import pickle
import os.path

def delta_epoch_type(x):
    x = int(x)
    if x < 3:
        raise argparse.ArgumentTypeError("Minimum delta epoch is 3, the default without any flags is 2 backwards")
    return x

parser=argparse.ArgumentParser(description='Get Vote Summary and Totals')
parser.add_argument('--service-name',type=str,nargs='?',default='validator.service',help='Service name for journalctl')
parser.add_argument('--build-indicesdb',action='store_true',default=False,help='Only biuld indices DB from initial startup logs')
group = parser.add_mutually_exclusive_group(required=False)
egroup = parser.add_mutually_exclusive_group(required=False)
egroup.add_argument('--epoch',type=int,nargs='?',help='Epoch number')
egroup.add_argument('--delta-epoch',type=delta_epoch_type,nargs='?',help='How many epochs backwards, minimum is 3')
group.add_argument('--bad',action='store_true',default=False,help='Show only bad votes')
group.add_argument('--neg',action='store_true',default=False,help='Show only negative votes')
args = parser.parse_args()

genesis=datetime.datetime(2020,12,1,12,0,23,0,tzinfo=timezone.utc)
if args.epoch != None:
  prev_epoch = args.epoch
else:
  now=datetime.datetime.utcnow()
  now=now.replace(tzinfo=timezone.utc)
  delta = now - genesis
  curr_epoch = math.floor(delta.total_seconds()/384)
  if args.delta_epoch != None:
    prev_epoch = curr_epoch - args.delta_epoch
  else:
    prev_epoch = curr_epoch - 2

rules = (Rule("_SYSTEMD_UNIT", args.service_name))
reader = JournalReader()
reader.open(JournalOpenMode.LOCAL_ONLY)
reader.add_filter(rules)

if args.build_indicesdb == False:
  estart = genesis + datetime.timedelta(0,prev_epoch*384)
  start_at = (estart.timestamp() - 12) * 1000000
  reader.seek_realtime_usec(start_at)

start_slot = prev_epoch * 32
end_slot = prev_epoch * 32 + 32
table = Table(title=f":scroll: Epoch {prev_epoch} ({start_slot}-{end_slot}) Vote Stats", header_style='bold magenta', show_header=True, show_lines=True)

table.row_styles = ['blue']
table.border_style = "bright_yellow"
#table.box = box.SIMPLE_HEAD
table.box=box.DOUBLE_EDGE

console = Console()
epoch_st = f"epoch={prev_epoch}"
duties={}
def get_attester_duties(dutymsg,epoch):
    p=r'([a-zA-Z]+)\=([0-9]+)'
    start_slot = epoch*32
    stop_slot = epoch*32+32
    res=dict(re.findall(p,dutymsg))
    if int(res['slot']) >= start_slot and int(res['slot']) <= stop_slot:
        pk=r'([a-zA-Z]+)\=\[(.+)\]'
        pres = dict(re.findall(pk, dutymsg))
        for pubkey in pres['pubKeys'].split(' '):
            duties[pubkey] = {"slot": res['slot']}

voting={}
def get_voting(votemsg, epoch):
    p=r'([a-zA-Z]+)\=([0-9\.a-z]+)'
    res=dict(re.findall(p,votemsg))
    if int(res['epoch']) == epoch:
        pt = r'time\=\"([0-9\-\:\s]+)\"'
        t = list(re.findall(pt,votemsg))[0].split(' ')[1]
        res['time'] = t
        voting[res['pubKey']] = res

if args.build_indicesdb == True:
  indices={}
else:
  if os.path.exists('indices.pkl'):
      with open('indices.pkl','rb') as f:
          indices = pickle.load(f)
          revindices = {}
          for ind,pubkey in indices.items():
              revindices[pubkey] = ind
  else:
      indices = {}

def get_indices(activemsg):
    p=r'([a-zA-Z]+)\=([0-9\.a-z]+)'
    res=dict(re.findall(p,activemsg))
    indices[res['index']] = res['publicKey']

getting_indices=False

submissions={}
def get_submissions(submsg, epoch):
    if len(duties.keys()) == 0:
        return

    pind=r'([a-zA-Z]+)\=\[([0-9\s]+)\]'
    indres=dict(re.findall(pind,submsg))
    pt = r'time\=\"([0-9\-\:\s]+)\"'
    tres=list(re.findall(pt,submsg))[0]
    p=r'([a-zA-Z]+)\=([0-9\.a-z]+)'
    res=dict(re.findall(p,submsg))
    for ind in indres['AttesterIndices'].split(' '):
        aggregators = []
        if 'AggregatorIndices' in indres:
            aggregators = indres['AggregatorIndices'].split(' ')
        aggregator = False
        if ind in aggregators:
            aggregator = True

        publicKey = indices[ind]
        slot = res['Slot']
        #if int(slot) < start_slot or int(slot) > end_slot:
        #    continue
        time = tres
        if slot == duties[publicKey]['slot']:
            submissions[publicKey] = {'ind': ind, 'time': time, 'slot':slot, 'aggregator': aggregator}

for record in reader:
    if not 'MESSAGE' in record.data.keys():
        continue

    msg=record.data['MESSAGE']
    if args.build_indicesdb:
        if "Validator activated" in msg:
            getting_indices=True
            get_indices(msg)
        else:
            if getting_indices:
                break #means we have started getting indices, and encountered the end of "Validator activated" messages
        continue

    if "Attestation schedule" in msg:
        get_attester_duties(msg, prev_epoch)
    if "Submitted new attestations" in msg:
        if len(indices.keys()) > 0:
          get_submissions(msg, prev_epoch)

    if "Previous epoch voting summary" in msg:
        if epoch_st in msg:
            get_voting(msg, prev_epoch)

if args.build_indicesdb:
    c = len(indices.keys())
    print(f"Done building db with {c} keys")
    with open('indices.pkl','wb') as f:
        pickle.dump(indices,f,protocol=-1)
    sys.exit(0)

def mark(str):
    if str == "true":
        return ":white_check_mark:"
    return ":cross_mark:"

if len(submissions.keys()) > 0:
    table.add_column("latency")
    table.add_column("indices")
else:
    table.add_column("time")
    table.add_column("pubkey")

table.add_column("epoch:slot")
table.add_column("sched slot")
table.add_column("target", justify='center')
table.add_column("source", justify='center')
table.add_column("head", justify='center')
#table.add_column("inc. dist")
table.add_column("score")
table.add_column("bal chg.")

agg_counter=0
wrong_head=0
wrong_source=0
wrong_target=0
total_income=0
for pubkey, vd in voting.items():
    new_bal = "{:.9f}".format(float(vd['newBalance']))
    old_bal = "{:.9f}".format(float(vd['oldBalance']))
    new_bal = int("".join(new_bal.split('.')))
    old_bal = int("".join(old_bal.split('.')))
    bd = str(new_bal - old_bal)
    total_income += (new_bal-old_bal)
    if args.bad and vd['correctlyVotedTarget']=='true' and vd['correctlyVotedSource']=='true' and vd['correctlyVotedHead']=='true':
      continue

    if args.neg and new_bal-old_bal > 0:
        continue

    rel_slot=str(int(duties[pubkey]['slot']) % 32)
    p = pubkey
    ss = duties[pubkey]['slot']
    if len(submissions.keys()) > 0:
        if submissions[pubkey]['slot'] == duties[pubkey]['slot']:
            submission_time = datetime.datetime.strptime(submissions[pubkey]['time'],'%Y-%m-%d %H:%M:%S')
            submission_time = submission_time.replace(tzinfo=timezone.utc)
            sched_time=genesis+datetime.timedelta(0,int(duties[pubkey]['slot'])*12)
            delta = submission_time - sched_time
            time = str(delta.seconds)
            delta_slot = int(submissions[pubkey]['slot']) - int(duties[pubkey]['slot'])
            ss = f"{ss} ({delta_slot})"
            if pubkey in revindices:
              agg = ""
              if submissions[pubkey]['aggregator']:
                  agg_counter+=1
                  agg = "AGG"
              p = f"{pubkey} ({revindices[pubkey]}) {agg}"
        else:
            time = vd['time']
    else:
        time = vd['time']

    if vd['correctlyVotedTarget'] != "true":
        wrong_target += 1
    if vd['correctlyVotedSource'] != "true":
        wrong_source += 1
    if vd['correctlyVotedHead'] != "true":
        wrong_head += 1

    table.add_row(time,p,f"{vd['epoch']}:{rel_slot}",ss,mark(vd['correctlyVotedTarget']),mark(vd['correctlyVotedSource']),mark(vd['correctlyVotedHead']),vd['inactivityScore'],bd)

total_income = total_income / (10**9)
table.add_row("totals", f"{len(voting.items())} active validators ({agg_counter} aggregators)", str(prev_epoch), "wrong totals:", str(wrong_target), str(wrong_source), str(wrong_head), "", f"{total_income} ETH")
console.print(table)
