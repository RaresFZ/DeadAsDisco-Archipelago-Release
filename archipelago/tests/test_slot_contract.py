import unittest
import tempfile
from pathlib import Path
from archipelago.client.slot_contract import SlotContract
from archipelago.client.reconciliation import ReconciliationError, Ledger, Binding


class SlotContractTests(unittest.TestCase):
    def setUp(self):
        self.catalog={'locations':[{'id':10},{'id':11}], 'items':[
            {'id':20,'classification':'progression'}, {'id':21,'classification':'filler'},
            {'id':22,'classification':'trap'}]}
        self.packet={'location_ids':[10], 'item_ids':[20], 'options':{'traps':False},
            'death_link':False,'goal':{'kind':0,'records':[11],'story_records':[11],'count':1}}

    def test_disabled_categories_and_traps_stay_excluded(self):
        contract=SlotContract(self.catalog,self.packet)
        self.assertEqual(contract.locations,{10})
        self.assertEqual(contract.items,{20,21})
        self.assertFalse(contract.death_link)
        self.packet['options']['traps']=True
        self.assertEqual(SlotContract(self.catalog,self.packet).items,{20,21,22})

    def test_duplicate_unknown_ids_and_impossible_goal_refused(self):
        for change in ({'location_ids':[10,10]},{'item_ids':[999]},
                {'death_link':1},{'goal':{'kind':0,'records':[11],'story_records':[11],'count':2}}):
            with self.subTest(change=change),self.assertRaises(ReconciliationError):
                SlotContract(self.catalog,{**self.packet,**change})

    def test_server_slot_zero_start_inventory_is_durable_and_idempotent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            ledger=Ledger(Path(root)/'ledger',Binding('seed',0,1,'generation','slot'))
            history=[[20,-2,0,1],[22,-2,0,4]]
            ledger.receive(0,history);ledger.receive(0,history)
            self.assertEqual(len(ledger.pending_items()),2)
            ledger.close()
