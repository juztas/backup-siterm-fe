#! /usr/bin/env python
# pylint: disable=line-too-long, bad-whitespace
"""
Site FE call functions

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
Date			: 2017/09/26
"""
from time import time
from tempfile import NamedTemporaryFile
from SiteFE.PolicyService import policyService as polS
from SiteFE.PolicyService import stateMachine as stateM
from DTNRMLibs.MainUtilities import httpdate
from DTNRMLibs.MainUtilities import getConfig
from DTNRMLibs.MainUtilities import contentDB
from DTNRMLibs.MainUtilities import getCustomOutMsg
from DTNRMLibs.MainUtilities import getAllFileContent
from DTNRMLibs.MainUtilities import convertTSToDatetime
from DTNRMLibs.CustomExceptions import DeltaNotFound
from DTNRMLibs.CustomExceptions import ModelNotFound
from DTNRMLibs.CustomExceptions import WrongDeltaStatusTransition
from DTNRMLibs.FECalls import getDBConn
from DTNRMLibs.MainUtilities import getVal

class frontendDeltaModels(object):
    """ Delta Actions through Frontend interface """
    def __init__(self, logger, config=None):
        self.dbI = getDBConn()
        self.config = getConfig(["/etc/dtnrm-site-fe.conf"])
        if config:
            self.config = config
        self.logger = logger
        self.policer = polS.PolicyService(self.config, self.logger)
        self.stateM = stateM.StateMachine(self.logger)
        self.siteDB = contentDB(logger=self.logger, config=self.config)

    def addNewDelta(self, uploadContent, environ, **kwargs):
        """ Add new delta """
        dbobj = getVal(self.dbI, **kwargs)
        hashNum = uploadContent['id']
        if dbobj.get('deltas', search=[['uid', hashNum]], limit=1):
            # This needs to be supported as it can be re-initiated again. TODO
            msg = 'Something weird has happened... Check server logs; Same ID is already in DB'
            kwargs['http_respond'].ret_409('application/json', kwargs['start_response'], None)
            return getCustomOutMsg(errMsg=msg, errCode=409)
        tmpfd = NamedTemporaryFile(delete=False)
        tmpfd.close()
        self.getmodel(uploadContent['modelId'], **kwargs)
        outContent = {"ID": hashNum,
                      "InsertTime": int(time()),
                      "UpdateTime": int(time()),
                      "Content": uploadContent,
                      "State": "accepting",
                      "modelId": uploadContent['modelId']}
        self.siteDB.saveContent(tmpfd.name, outContent)
        out = self.policer.acceptDelta(tmpfd.name, kwargs['sitename'])
        outDict = {'id': hashNum,
                   'lastModified': convertTSToDatetime(outContent['UpdateTime']),
                   'href': "%s/%s" % (environ['SCRIPT_URI'], hashNum),
                   'modelId': out['modelId'],
                   'state': out['State'],
                   'reduction': out['ParsedDelta']['reduction'],
                   'addition': out['ParsedDelta']['addition']}
        print 'Delta was %s. Returning info %s' % (out['State'], outDict)
        if out['State'] in ['accepted']:
            kwargs['http_respond'].ret_201('application/json', kwargs['start_response'],
                                           [('Last-Modified', httpdate(out['UpdateTime'])),
                                            ('Location', outDict['href'])])
            return outDict
        else:
            kwargs['http_respond'].ret_500('application/json', kwargs['start_response'], None)
            if 'Error' in out.keys():
                errMsg = ""
                for key in ['errorNo', 'errorType', 'errMsg']:
                    if key in out['Error'].keys():
                        errMsg += " %s: %s" % (key, out['Error'][key])
            return getCustomOutMsg(errMsg=errMsg, exitCode=500)

    def getdelta(self, deltaID=None, **kwargs):
        """ Get delta from file """
        dbobj = getVal(self.dbI, **kwargs)
        if not deltaID:
            return dbobj.get('deltas')
        out = dbobj.get('deltas', search=[['uid', deltaID]])
        if not out:
            raise DeltaNotFound("Delta with %s id was not found in the system" % deltaID)
        return out[0]

    def getHostNameIDs(self, hostname, state, **kwargs):
        """ Get Hostname IDs """
        dbobj = getVal(self.dbI, **kwargs)
        return dbobj.get('hoststates', search=[['hostname', hostname], ['state', state]])

    def getmodel(self, modelID=None, content=False, **kwargs):
        """ Get all models """
        dbobj = getVal(self.dbI, **kwargs)
        if not modelID:
            return dbobj.get('models', orderby=['insertdate', 'DESC'])
        model = dbobj.get('models', limit=1, search=[['uid', modelID]])
        if not model:
            raise ModelNotFound("Model with %s id was not found in the system" % modelID)
        if content:
            return getAllFileContent(model[0]['fileloc'])
        return model[0]

    def commitdelta(self, deltaID, newState='UNKNOWN', internal=False, hostname=None, **kwargs):
        """ Change delta state """
        dbobj = getVal(self.dbI, **kwargs)
        if internal:
            out = dbobj.get('hoststates', search=[['deltaid', deltaID], ['hostname', hostname]])
            if not out:
                msg = 'This query did not returned any host states for %s %s' % (deltaID, hostname)
                raise WrongDeltaStatusTransition(msg)
            self.stateM._stateChangerHost(dbobj, out[0]['id'], **{'deltaid': deltaID,
                                                                  'state': newState,
                                                                  'insertdate': int(time()),
                                                                  'hostname': hostname})
            return getCustomOutMsg(msg='Internal State change approved', exitCode=200)
        else:
            delta = self.getdelta(deltaID, **kwargs)
            print 'Commit Action for delta %s' % delta
            # Now we go directly to commited in case of commit
            if delta['state'] != 'accepted':
                msg = "Delta    state in the system is not in accepted state. \
                      State on the system: %s. Not allowed to change." % delta['state']
                print msg
                raise WrongDeltaStatusTransition(msg)
            self.stateM.commit(dbobj, {'uid': deltaID, 'state': 'committing'})
