#
# Easy Computer Vision
#
# easy.py is a high-level interface to CVAC, the
# Computer Vision Algorithm Collection.
#
from __future__ import print_function
import os
import sys, traceback
# paths should setup the PYTHONPATH.  If you special requirements
# then use the following to set it up prior to running.
# export PYTHONPATH="/opt/Ice-3.4.2/python:./src/easy"
import paths
sys.path.append('''.''')
import Ice
import Ice
import IcePy
import cvac
import unittest
import stat
import threading

#
# one-time initialization code, upon loading the module
#
ic = Ice.initialize(sys.argv)
defaultCS = None


def getFSPath( cvacPath ):
    '''Turn a CVAC path into a file system path'''
    # todo: obtain CVAC.DataDir
    CVAC_DataDir = "data"
    path = CVAC_DataDir+"/"+cvacPath.directory.relativePath+"/"+cvacPath.filename
    return path

def getCvacPath( fsPath ):
    '''Turn a file system path into a CVAC FilePath'''
    # todo: should figure out what CVAC.DataDir is and parse that out, too
    drive, path = os.path.splitdrive( fsPath )
    path, filename = os.path.split( path )
    dataRoot = cvac.DirectoryPath( path );
    return cvac.FilePath( dataRoot, filename )

def isLikelyVideo( cvacPath ):
    videoExtensions = ['avi', 'mpg', 'wmv']
    for ext in videoExtensions:
        if cvacPath.filename.endswith(ext):
            return True
    return False

def getLabelable( cvacPath, labelText=None ):
    '''Create a Labelable wrapper around the file, assigning
    a textual label if specified.'''
    if labelText:
        label = cvac.Label( True, labelText, None, cvac.Semantics() )
    else:
        label = cvac.Label( False, "", None, cvac.Semantics() )
    isVideo = isLikelyVideo( cvacPath )
    substrate = cvac.Substrate( not isVideo, isVideo, cvacPath, 0, 0 )
    labelable = cvac.Labelable( 0.0, label, substrate )
    return labelable

def getCorpusServer( configstr ):
    '''Connect to a Corpus server based on the given configuration string'''
    cs_base = ic.stringToProxy( configstr )
    if not cs_base:
        raise RuntimeError("CorpusServer not found in config:", configstr)
    cs = cvac.CorpusServicePrx.checkedCast(cs_base)
    if not cs:
        raise RuntimeError("Invalid CorpusServer proxy")
    return cs

def getDefaultCorpusServer():
    '''Returns the CorpusServer that is expected to run locally at port 10011'''
    global defaultCS
    if not defaultCS:
        defaultCS = getCorpusServer( "CorpusServer:default -p 10011" )
    return defaultCS

def openCorpus( corpusServer, corpusPath ):
    '''Open a Corpus specified by a properties file,
       or create a new Corpus from all files in a given directory'''
    # switch based on whether corpusPath is likely a directory or not.
    # note that the corpus could be on a remote server, therefore
    # we can't check for existence and type of corpusPath (dir, file)
    # but instead have to guess from the file extension, if any
    likelyDir = False
    dotidx = corpusPath.rfind(".")  # find last .
    if dotidx is -1:
        likelyDir = True
    else:
        sepidx = corpusPath[dotidx:].rfind("/") # any / after .?
        if sepidx>-1:
            likelyDir = True
        
    if likelyDir:
        # create a new corpus
        cvacPath = cvac.DirectoryPath( corpusPath )
        corpus = corpusServer.createCorpus( cvacPath )
        if not corpus:
            raise RuntimeError("Could not create corpus from directory at '"
                               + getFSPath( cvacPath ))
    else:
        # open an existing corpus
        cvacPath = getCvacPath( corpusPath )
        corpus = corpusServer.openCorpus( cvacPath )
        if not corpus:
            raise RuntimeError("Could not open corpus from properties file '"
                               + getFSPath( cvacPath ))
    return corpus

class CorpusCallbackI(cvac.CorpusCallback):
    corpus = None
    def corpusMirrorProgress( corp, numtasks, currtask, taskname, details,
            percentCompleted ):
        print("Downloading corpus {0}, task {1}/{2}: {3} ({4}%)".\
              format( corp.name, currtask, numtasks, taskname ))
    def corpusMirrorCompleted(self, corp):
        self.corpus = corp

def createLocalMirror( corpusServer, corpus ):
    '''Call the corpusServer to create the local mirror for the
    specified corpus.  Provide a simple callback for tracking.'''
    # ICE functionality to enable bidirectional connection for callback
    adapter = ic.createObjectAdapter("")
    cbID = Ice.Identity()
    cbID.name = Ice.generateUUID()
    cbID.category = ""
    callbackRecv = CorpusCallbackI()
    adapter.add( callbackRecv, cbID)
    adapter.activate()
    corpusServer.ice_getConnection().setAdapter(adapter)
    # this call should block
    corpusServer.createLocalMirror( corpus, cbID )
    if not callbackRecv.corpus:
        raise RuntimeError("could not create local mirror")

def getDataSet( corpus, corpusServer=None, createMirror=False ):
    '''Obtain the set of labels from the given corpus and return it as
    a dictionary of label categories.  Also return a flat list of all labels.
    The default local corpusServer is used if not explicitly specified.
    If the corpus argument is not given as an actual cvac.Corpus object
    but the argument is a string instead, an attempt is made to
    open (but not create) a Corpus object from the corpusServer.
    Note that this will fail if the corpus needs a local mirror but has not
    been downloaded yet, unless createMirror=True.'''

    # get the default CorpusServer if not explicitly specified
    if not corpusServer:
        corpusServer = getDefaultCorpusServer()

    if type(corpus) is str:
        corpus = openCorpus( corpusServer, corpus )
    elif not type(corpus) is cvac.Corpus:
        raise RuntimeError( "unexpected type for corpus:", type(corpus) )

    # print 'requires:', corpusServer.getDataSetRequiresLocalMirror( corpus )
    # print 'exists:', corpusServer.localMirrorExists( corpus )
    if corpusServer.getDataSetRequiresLocalMirror( corpus ) \
        and not corpusServer.localMirrorExists( corpus ):
        if createMirror:
            createLocalMirror( corpusServer, corpus )
        else:
            raise RuntimeError("local mirror required, won't create automatically",
                               "(specify createMirror=True to do so)")

    labelList = corpusServer.getDataSet( corpus )
    categories = {}
    for lb in labelList:
        if lb.lab.name in categories:
            categories[lb.lab.name].append( lb )
        else:
            categories[lb.lab.name] = [lb]
    return (categories, labelList)

def printCategoryInfo( categories ):
    if not categories:
        print("no categories, nothing to print")
        return
    sys.stdout.softspace=False;
    for key in sorted( categories.keys() ):
        klen = len( categories[key] )
        print("{0} ({1} artifact{2})".format( key, klen, ("s","")[klen==1] ))

def createRunSet( categories ):
    '''Add all samples from the categories to a new RunSet.
    Determine whether this is a two-class (positive and negative)
    or a multiclass dataset and create the RunSet appropriately.
    Input argument can also be a string to a single file.
    Note that the positive and negative classes might not be
    determined correctly automatically.
    Return the mapping from Purpose (class ID) to label name.'''

    runset = None
    if type(categories) is dict:
        # multiple categories
        classmap = {}
        pur_categories = []
        pur_categories_keys = sorted( categories.keys() )

        # if it's two classes, maybe one is called "pos" and the other "neg"?
        if len(categories) is 2:
            alow = pur_categories_keys[0].lower()
            blow = pur_categories_keys[1].lower()
            poskeyid = -1
            if "pos" in alow and "neg" in blow:
                # POSITIVES in keys[0]
                poskeyid = 0
            elif "neg" in alow and "pos" in blow:
                # POSITIVES in keys[1]
                poskeyid = 1
            if poskeyid != -1:
                pospur = cvac.Purpose( cvac.PurposeType.POSITIVE, -1 )
                negpur = cvac.Purpose( cvac.PurposeType.NEGATIVE, -1 )
                poskey = pur_categories_keys[poskeyid]
                negkey = pur_categories_keys[1-poskeyid]
                pur_categories.append( cvac.PurposedLabelableSeq( \
                    pospur, categories[poskey] ) )
                pur_categories.append( cvac.PurposedLabelableSeq( \
                    negpur, categories[negkey] ) )
                runset = cvac.RunSet( pur_categories )
                classmap[poskey] = pospur
                classmap[negkey] = negpur
                return {'runset':runset, 'classmap':classmap}

        # multi-class
        cnt = 0
        for key in pur_categories_keys:
            purpose = cvac.Purpose( cvac.PurposeType.MULTICLASS, cnt )
            classmap[key] = purpose
            pur_categories.append( cvac.PurposedLabelableSeq( purpose, categories[key] ) )
            cnt = cnt+1
            runset = cvac.RunSet( pur_categories )
            
        return {'runset':runset, 'classmap':classmap}

    elif type(categories) is list and len(categories)>0 and type(categories[0]) is cvac.Labelable:
        # single category - assume "unlabeled"
        purpose = cvac.Purpose( cvac.PurposeType.UNLABELED )
        plists = [ cvac.PurposedLabelableSeq( purpose, categories ) ]
        runset = cvac.RunSet( plists )
        return {'runset':runset, 'classmap':None}

    elif type(categories) is str:
        # single file, create an unlabeled entry
        fpath = getCvacPath( categories )
        labelable = getLabelable( fpath )
        purpose = cvac.Purpose( cvac.PurposeType.UNLABELED )
        plists = [ cvac.PurposedLabelableSeq( purpose, [labelable] ) ]
        runset = cvac.RunSet( plists )
        return {'runset':runset, 'classmap':None}
        
    else:
        raise RuntimeError( "don't know how to create a RunSet from ", type(categories) )

def getFileServer( configString ):
    '''Obtain a reference to a remote FileServer.
    Generally, every host of CVAC services also has one FileServer.'''
    fileserver_base = ic.stringToProxy( configString )
    if not fileserver_base:
        raise RuntimeError("no such FileService: "+configString)
    fileserver = cvac.FileServicePrx.checkedCast( fileserver_base )
    if not fileserver:
        raise RuntimeError("Invalid FileServer proxy")
    return fileserver

def getDefaultFileServer( detector ):
    '''Assume that a FileServer is running on the host of the detector
    at the default port (10110).  Obtain a connection to that.'''
    # what host is the detector running on?
    endpoints = detector.ice_getEndpoints()
    # debug output:
    #print endpoints
    #print type(endpoints[0])
    #print dir(endpoints[0])
    #print endpoints[0].getInfo()
    #print endpoints[0].getInfo().type()
    #print dir(endpoints[0].getInfo().type())
    #print "host: ", endpoints[0].getInfo().host, "<-"
    # expect to see only one Endpoint, of type IP
    if not len(endpoints) is 1:
        raise RuntimeError( "don't know how to deal with more than one Endpoint" )
    if not isinstance( endpoints[0].getInfo(), IcePy.IPEndpointInfo ):
        raise RuntimeError( "detector has unexpected endpoint(s):", endpoints )
    host = endpoints[0].getInfo().host

    # if host is empty, the detector is probably a local service and
    # there is no Endpoint
    if not host:
        host = "localhost"

    # get the FileServer at said host at the default port
    configString = "FileService:default -h "+host+" -p 10110"
    try:
        fs = getFileServer( configString )
    except RuntimeError:
        raise RuntimeError( "No default FileServer at the detector's host",
                            host, "on port 10110" )
    return fs

def putFile( fileserver, filepath ):
    origFS = getFSPath( filepath )
    if not os.path.exists( origFS ):
        raise RuntimeError("Cannot obtain FS path to local file:",origFS)
    forig = open( origFS, 'rb' )
    bytes = bytearray( forig.read() )
    
    # "put" the file's bytes to the FileServer
    fileserver.putFile( filepath, bytes );
    forig.close()

def collectSubstrates( runset ):
    '''obtain a set (a list without duplicates) of all
    substrates that occur in this runset'''
    substrates = set()
    for plist in runset.purposedLists:
        if type(plist) is cvac.PurposedDirectory:
            raise RuntimeException("cannot deal with PurposedDirectory yet")
        elif type(plist) is cvac.PurposedLabelableSeq:
            for lab in plist.labeledArtifacts:
                if not lab.sub in substrates:
                    substrates.add( lab.sub )
        else:
            raise RuntimeException("unexpected subclass of PurposedList")
    return substrates

def putAllFiles( fileserver, runset ):
    '''Make sure all files in the RunSet are available on the remote site;
    it is the client\'s responsibility to upload them if not.
    For reporting purposes, return what has and has not been uploaded.'''
    assert( fileserver and runset )

    # collect all "substrates"
    substrates = collectSubstrates( runset )
    
    # upload if not present
    uploadedFiles = []
    existingFiles = []
    for sub in substrates:
        if not type(sub) is cvac.Substrate:
            raise RuntimeError("Unexpected type found instead of cvac.Substrate:", type(sub))
        if not fileserver.exists( sub.path ):
            putFile( fileserver, sub.path )
            uploadedFiles.append( sub.path )
        else:
            existingFiles.append( sub.path )

    return {'uploaded':uploadedFiles, 'existing':existingFiles}

def deleteAllFiles( fileserver, uploadedFiles ):
    '''Delete all files that were previously uploaded to the fileserver.
    For reporting purposes, return what has and has not been uploaded.'''
    assert( fileserver )

    # are there any files to delete?
    if not uploadedFiles:
        return

    # try top delete, ignore but log errors
    deletedFiles = []
    notDeletedFiles = []
    for path in uploadedFiles:
        if not type(path) is cvac.FilePath:
            raise RuntimeError("Unexpected type found instead of cvac.FilePath:", type(path))
        try:
            fileserver.deleteFile( path )
            deletedFiles.append( path )
        except cvac.FileServiceException:
            notDeletedFiles.append( path )

    return {'deleted':deletedFiles, 'notDeleted':notDeletedFiles}

def getTrainer( configString ):
    '''Connect to a trainer service'''
    trainer_base = ic.stringToProxy( configString )
    trainer = cvac.DetectorTrainerPrx.checkedCast( trainer_base )
    if not trainer:
        raise RuntimeError("Invalid DetectorTrainer proxy")
    return trainer

# a default implementation for a TrainerCallbackHandler, in case
# the easy user doesn't specify one;
# this will get called once the training is done
class TrainerCallbackReceiverI(cvac.TrainerCallbackHandler):
    detectorData = None
    trainingFinished = False
    def createdDetector(self, detData, current=None):
        if not detData:
            raise RuntimeError("Finished training, but obtained no DetectorData")
        print("Finished training, obtained DetectorData of type", detData.type)
        self.detectorData = detData
        self.trainingFinished = True

def train( trainer, runset, callbackRecv=None ):
    '''A callback receiver can optionally be specified'''
    
    # ICE functionality to enable bidirectional connection for callback
    adapter = ic.createObjectAdapter("")
    cbID = Ice.Identity()
    cbID.name = Ice.generateUUID()
    cbID.category = ""
    if not callbackRecv:
        callbackRecv = TrainerCallbackReceiverI()
    adapter.add( callbackRecv, cbID)
    adapter.activate()
    trainer.ice_getConnection().setAdapter(adapter)

    # connect to trainer, initialize with a verbosity value, and train
    trainer.initialize( 3 )
    if type(runset) is dict:
        runset = runset['runset']
    trainer.process( cbID, runset )

    # check results
    if not callbackRecv.detectorData:
        raise RuntimeError("no DetectorData received from trainer")    
    if callbackRecv.detectorData.type == cvac.DetectorDataType.BYTES:
        raise RuntimeError('detectorData as BYTES has not been tested yet')
    elif callbackRecv.detectorData.type == cvac.DetectorDataType.PROVIDER:
        raise RuntimeError('detectorData as PROVIDER has not been tested yet')

    return callbackRecv.detectorData

def getDetector( configString ):
    '''Connect to a detector service'''
    detector_base = ic.stringToProxy( configString )
    detector = cvac.DetectorPrx.checkedCast(detector_base)
    if not detector:
        raise RuntimeError("Invalid Detector service proxy")
    return detector

# a default implementation for a DetectorCallbackHandler, in case
# the easy user doesn't specify one;
# this will get called when results have been found;
# replace the multiclass-ID label with the string label
class DetectorCallbackReceiverI(cvac.DetectorCallbackHandler):
    allResults = []
    detectionFinished = False
    def foundNewResults(self, r2, current=None):
        # collect all results
        self.allResults.extend( r2.results )

def detect( detector, detectorData, runset, callbackRecv=None ):
    '''Synchronously run detection with the specified detector,
    trained model, and optional callback receiver.
    The detectorData can be either a cvac.DetectorData object or simply
     a filename of a pre-trained model.  Naturally, the model has to be
     compatible with the detector.
    The runset can be either a cvac.RunSet object, filename to a single
     file that is to be tested, or a directory path.
    If a callback receiver is specified, this function returns nothing,
    otherwise, the obtained results are returned.'''

    # create a cvac.DetectorData object out of a filename
    if type(detectorData) is str:
        ddpath = getCvacPath( detectorData );
        detectorData = cvac.DetectorData( cvac.DetectorDataType.FILE, None, ddpath, None )
    elif not type(detectorData) is cvac.DetectorData:
        raise RuntimeException("detectorData must be either filename or cvac.DetectorData")

    # create a RunSet out of a filename or directory path
    if type(runset) is str:
        res = createRunSet( runset )
        runset = res['runset']
        classmap = res['classmap']
    elif not type(runset) is cvac.RunSet:
        raise RuntimeException("runset must either be a filename, directory, or cvac.RunSet")

    # ICE functionality to enable bidirectional connection for callback
    adapter = ic.createObjectAdapter("")
    cbID = Ice.Identity()
    cbID.name = Ice.generateUUID()
    cbID.category = ""
    ourRecv = False  # will we use our own simple callback receiver?
    if not callbackRecv:
        ourRecv = True
        callbackRecv = DetectorCallbackReceiverI();
    adapter.add( callbackRecv, cbID )
    adapter.activate()
    detector.ice_getConnection().setAdapter(adapter)

    # connect to detector, initialize with a verbosity value
    # and the trained model, and run the detection on the runset
    detector.initialize( 3, detectorData )
    detector.process( cbID, runset )

    if ourRecv:
        return callbackRecv.allResults

def getPurposeName( purpose ):
    '''Returns a string to identify the purpose or an
    int to identify a multiclass class ID.'''
    if purpose.ptype is cvac.PurposeType.UNLABELED:
        return "unlabeled"
    elif purpose.ptype is cvac.PurposeType.POSITIVE:
        return "positive"
    elif purpose.ptype is cvac.PurposeType.NEGATIVE:
        return "negative"
    elif purpose.ptype is cvac.PurposeType.MULTICLASS:
        return purpose.classID
    elif purpose.ptype is cvac.PurposeType.ANY:
        return "any"
    else:
        raise RuntimeError("unexpected cvac.PurposeType")

def getLabelText( label, classmap=None ):
    '''Return a label text for the label: either
    "unlabeled" or the name of the label or whatever
    Purpose this label maps to.'''
    if not label.hasLabel:
        return "unlabeled"
    text = label.name
    if classmap and text in classmap:
        mapped = classmap[text]
        if type(mapped) is cvac.Purpose:
            text = getPurposeName( mapped )
            if type(text) is int:
                text = 'class {0}'.format( text )
        elif type(mapped) is str:
            text = mapped
        else:
            raise RuntimeError( "unexpected type for classmap elements: "+
                                type(mapped) )
    return text

def printResults( results, foundMap=None, origMap=None ):
    '''Print detection results as specified in a ResultSet.
    If classmaps are specified, the labels are mapped
    (replaced by) purposes: the foundMap maps found labels and
    the origMap maps the original labels, if any.
    The classmap is a dictionary mapping either label to Purpose
    or label to string.  Since detectors do not produce Purposes,
    but the foundMap maps labels to Purposes, it is assumed that
    the users wishes to replace a label that hints at the Purpose
    with the label that maps to that same Purpose.  For example,
    a result label of '12' is assumed to be a class ID.  The
    classmap might map 'face' to a Purpose(MULTICLASS, 12).
    Hence, we would replace '12' with 'face'.'''
    
    # create inverse map for found labels
    labelPurposeLabelMap = {}
    if foundMap:
        for key in foundMap.keys():
            pur = foundMap[key]
            if not type(pur) is cvac.Purpose:
                break
            id = getPurposeName( pur )
            if type(id) is int:
                id = str(id)
            labelPurposeLabelMap[id] = key
    if labelPurposeLabelMap:
        foundMap = labelPurposeLabelMap
    
    print('received a total of {0} results:'.format( len( results ) ))
    identical = 0
    for res in results:
        names = []
        for lbl in res.foundLabels:
            foundLabel = getLabelText( lbl.lab, foundMap )
            names.append(foundLabel)
        numfound = len(res.foundLabels)
        origname = getLabelText( res.original.lab, origMap )
        print("result for {0} ({1}): found {2} label{3}: {4}".format(
            res.original.sub.path.filename, origname,
            numfound, ("s","")[numfound==1], ', '.join(names) ))
        if numfound==1 and origname.lower()==names[0].lower():
            identical += 1
    print('{0} out of {1} results had identical labels'.format( identical, len( results ) ))

def getConfusionMatrix( results, origMap, foundMap ):
    '''produce a confusion matrix'''
    import numpy
    catsize = len( origMap )
    if catsize>50:
        pass
    confmat = numpy.empty( (catsize+1, catsize+1) )
    return confmat
