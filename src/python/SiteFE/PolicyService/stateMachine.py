#!/usr/bin/env python
"""
Everything goes here when they do not fit anywhere else

Copyright 2017 California Institute of Technology
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
Title 			: dtnrm
Author			: Justas Balcas
Email 			: justas.balcas (at) cern.ch
@Copyright		: Copyright (C) 2016 California Institute of Technology
Date			: 2018/11/26
"""
import time
from DTNRMLibs.MainUtilities import evaldict


def timeendcheck(delta, logger):
    """ Check delta timeEnd. if passed, returns True. """
    try:
        if 'timeend' in delta['addition'].keys():
            timeleft = int(time.time()) - int(delta['addition']['timeend'])
            logger.info('CurrentTime %s TimeStart %s. TimeLeft %s'
                        % (int(time.time()), delta['addition']['timeend'], timeleft))
            if delta['addition']['timeend'] < int(time.time()):
                logger.info('This delta already passed timeend mark. Setting state to cancel')
                return True
            else:
                logger.info('Time did not passed yet.')
        else:
            logger.info('There is no timeend defined inside the Parsed Delta')
    except:
        logger.info('This delta had an error checking endtime. Leaving state as it is.')
    return False


class StateMachine(object):
    """ State machine for Frontend and policy service """
    def __init__(self, logger):
        self.logger = logger
        self.limit = 100
        return

    def _stateChangerDelta(self, dbObj, newState, **kwargs):
        tNow = int(time.time())
        self.logger.info('Changing delta %s to %s' % (kwargs['uid'], newState))
        dbObj.update('deltas', [{'uid': kwargs['uid'],
                                 'state': newState,
                                 'updatedate': tNow}])
        dbObj.insert('states', [{'deltaid': kwargs['uid'],
                                 'state': newState,
                                 'insertdate': tNow}])

    def _modelstatechanger(self, dbObj, newState, **kwargs):
        tNow = int(time.time())
        dbObj.update('deltasmod', [{'uid': kwargs['uid'],
                                    'modadd': newState,
                                    'updatedate': tNow}])


    def modelstatecancel(self, dbObj, **kwargs):
        if kwargs['modadd'] in ['idle']:
            self._modelstatechanger(dbObj, 'removed', **kwargs)
        elif kwargs['modadd'] in ['add', 'added']:
            self._modelstatechanger(dbObj, 'remove', **kwargs)

    def _stateChangerHost(self, dbObj, hid, **kwargs):
        tNow = int(time.time())
        self.logger.info('Changing delta %s hoststate %s to %s' %
                         (kwargs['deltaid'], kwargs['hostname'], kwargs['state']))
        dbObj.update('hoststates', [{'deltaid': kwargs['deltaid'],
                                     'state': kwargs['state'],
                                     'updatedate': tNow,
                                     'id': hid}])
        dbObj.insert('hoststateshistory', [kwargs])

    def _newdelta(self, dbObj, delta, state):
        dbOut = {'uid': delta['ID'],
                 'insertdate': int(delta['InsertTime']),
                 'updatedate': int(delta['UpdateTime']),
                 'state': str(state),
                 'deltat': str(delta['Type']),
                 'content': str(delta['Content']),
                 'modelid': str(delta['modelId']),
                 'reduction': str(delta['ParsedDelta']['reduction']),
                 'addition': str(delta['ParsedDelta']['addition']),
                 'reductionid': '' if 'ReductionID' not in delta.keys() else delta['ReductionID'],
                 'modadd': str(delta['modadd']),
                 'connectionid': str(delta['ConnID']),
                 'error': '' if 'Error' not in delta.keys() else str(delta['Error'])} # TODO Use error
        dbObj.insert('deltas', [dbOut])
        dbOut['state'] = delta['State']
        self._stateChangerDelta(dbObj, delta['State'], **dbOut)

    def _newhoststate(self, dbObj, **kwargs):
        """ Private to add new host states. """
        tNow = int(time.time())
        kwargs['insertdate'] = tNow
        kwargs['updatedate'] = tNow
        dbObj.insert('hoststates', [kwargs])

    def accepted(self, dbObj, delta):
        """ Marks delta as accepting """
        self._newdelta(dbObj, delta, 'accepting')

    def commit(self, dbObj, delta):
        """ Marks delta as committing """
        self._stateChangerDelta(dbObj, 'committing', **delta)

    def committing(self, dbObj):
        """ Committing state Check """
        for delta in dbObj.get('deltas', search=[['state', 'committing']]):
            self._stateChangerDelta(dbObj, 'committed', **delta)
            self._modelstatechanger(dbObj, 'add', **delta)
        return

    def committed(self, dbObj):
        """ Committing state Check """
        for delta in dbObj.get('deltas', search=[['state', 'committed']]):
            if 'addition' in delta.keys() and delta['addition']:
                delta['addition'] = evaldict(delta['addition'])
                # Check the times...
                try:
                    if 'timestart' in delta['addition'].keys():
                        timeleft = int(delta['addition']['timestart']) - int(time.time())
                        self.logger.info('CurrentTime %s TimeStart %s. Seconds Left %s' %
                                         (int(time.time()), delta['addition']['timestart'], timeleft))
                        if delta['addition']['timestart'] < int(time.time()):
                            self.logger.info('This delta already passed timestart mark. Setting state to activating')
                            self._stateChangerDelta(dbObj, 'activating', **delta)
                        else:
                            self.logger.info('This delta did not passed timestart mark. Leaving state as it is')
                    else:
                        self.logger.info('This delta do not have timestart. Setting state to activating')
                        self._stateChangerDelta(dbObj, 'activating', **delta)
                except:
                    self.logger.info('This delta had an error checking starttime. Leaving state as it is.')
            else:
                self.logger.info('This delta is in committed. Setting state to activating.')
                self._stateChangerDelta(dbObj, 'activating', **delta)

    def activating(self, dbObj):
        """ Check on all deltas in state activating. """
        for delta in dbObj.get('deltas', search=[['state', 'activating']]):
            delta['addition'] = evaldict(delta['addition'])
            delta['reduction'] = evaldict(delta['reduction'])
            for actionKey in ['reduction', 'addition']:
                if delta[actionKey].keys() and delta['deltat'] == 'addition':
                    hostStates = {}
                    for hostname in delta[actionKey]['hosts'].keys():
                        host = dbObj.get('hoststates', search=[['deltaid', delta['uid']], ['hostname', hostname]])
                        if host:
                            hostStates[host[0]['state']] = hostname
                        else:
                            self._newhoststate(dbObj, **{'hostname': hostname,
                                                         'state': 'activating',
                                                         'deltaid': delta['uid']})
                            hostStates['unset'] = hostname
                if actionKey == 'reduction' and delta['deltat'] == 'reduction':
                    tmpID = delta['reductionid']
                    self.logger.info('Reduction for %s....' % tmpID)
                    for delta1 in dbObj.get('deltas', search=[['uid', tmpID]], limit=1):
                        currentState = delta1["state"]
                        if currentState not in ['removing', 'remove', 'cancel']:
                            self._stateChangerDelta(dbObj, 'removing', **delta1)
                        self._stateChangerDelta(dbObj, 'activated', **delta)
                elif actionKey == 'addition' and delta['deltat'] == 'addition':
                    if timeendcheck(delta, self.logger):
                        self._stateChangerDelta(dbObj, 'cancel', **delta)
                        self.modelstatecancel(dbObj, **delta)
                    if hostStates.keys() == ['active']:
                        self._stateChangerDelta(dbObj, 'activated', **delta)
                    elif 'failed' in hostStates.keys():
                        self._stateChangerDelta(dbObj, 'failed', **delta)

    def activated(self, dbObj):
        """ Check on all activated state deltas """
        for delta in dbObj.get('deltas', search=[['state', 'activated']]):
            # Reduction
            if delta['deltat'] in ['reduction']:
                if delta['updatedate'] < int(time.time() - 600):
                    self._stateChangerDelta(dbObj, 'removing', **delta)
                continue
            # Addition
            delta['addition'] = evaldict(delta['addition'])
            if timeendcheck(delta, self.logger):
                self._stateChangerDelta(dbObj, 'cancel', **delta)
                self.modelstatecancel(dbObj, **delta)

    def remove(self, dbObj):
        """ Check on all remove state deltas """
        for delta in dbObj.get('deltas', search=[['state', 'remove']]):
            if delta['updatedate'] < int(time.time() - 600):
                self._stateChangerDelta(dbObj, 'removed', **delta)
                self.modelstatecancel(dbObj, **delta)
        return

    def removing(self, dbObj):
        """ Check on all removing state deltas. Sets state remove """
        for delta in dbObj.get('deltas', search=[['state', 'removing']]):
            self._stateChangerDelta(dbObj, 'remove', **delta)
            self.modelstatecancel(dbObj, **delta)

    def cancel(self, dbObj):
        """ Check on all cancel state deltas. Sets state remove """
        for delta in dbObj.get('deltas', search=[['state', 'cancel']]):
            self._stateChangerDelta(dbObj, 'remove', **delta)
            self.modelstatecancel(dbObj, **delta)

    def failed(self, dbObj, delta):
        """ Marks delta as failed. This is only during submission """
        self._newdelta(dbObj, delta, 'accepting')
