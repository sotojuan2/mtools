from pymongo import Connection
from pymongo.errors import OperationFailure
from bson.son import SON
from bson.min_key import MinKey
import argparse

def presplit(host, database, collection, shardkey, shardnumber=None):
    """ get information about the number of shards, then split chunks and 
        distribute over shards. Currently assumes shardkey to be hex string,
        for example ObjectId or UUID. 

        host: host and port to connect to, e.g. "192.168.0.1:27017", "localhost:30000"
        database: database name to enable sharding
        collection: collection name to shard 
        shardkey: shardkey to pre-split on (must be hex string, e.g. ObjectId or UUID)
        shardnumber: if None, automatically presplit over all available shards. 
            if integer, only presplit over the given number of shards (maximum is 
            the number of actual shards)
    """
    
    con = Connection(host)
    namespace = '%s.%s'%(database, collection)

    # disable balancer
    con['config']['settings'].update({'_id':"balancer"}, {'$set':{'stopped': True}}, upsert=True)

    # enable sharding on database if not yet enabled
    db_info = con['config']['databases'].find_one({'_id':database})
    if not db_info or db_info['partitioned'] == False:
        con['admin'].command(SON({'enableSharding': database}))

    # shard collection if not yet sharded
    coll_info = con['config']['collections'].find_one({'_id':namespace})
    if coll_info and not coll_info['dropped']:
        # if it is sharded already, quit. something is not right.
        print "collection already sharded."
        return
    else:
        con[database][collection].ensure_index(shardkey)
        con['admin'].command(SON({'shardCollection': namespace, 'key': {shardkey:1}}))

    # get shard number and names and calculate split points
    shards = list(con['config']['shards'].find())

    if len(shards) == 1:
        print "only one shard found. no pre-splitting required."
        return

    # limit number of shards if shardnumber given
    if shardnumber and shardnumber <= len(shards):
        shards = shards[:shardnumber]

    shard_names = [s['_id'] for s in shards]
    split_interval = 16 / len(shards)
    split_points = [hex(s).lstrip('0x') for s in range(split_interval, len(shards)*split_interval, split_interval)]
    
    # pre-splitting commands
    for s in split_points:
        con['admin'].command(SON([('split',namespace), ('middle', {shardkey: s})]))
    
    split_points = [MinKey()] + split_points

    # move chunks to shards (catch the one error where the chunk resides on that shard already)
    for i,s in enumerate(split_points):
        try:
            print 'moving chunk %s in collection %s to shard %s.'%(s, namespace, shard_names[i])
            res = con['admin'].command(SON([('moveChunk',namespace), ('find', {shardkey: s}), ('to', shard_names[i])]))
        except OperationFailure, e:
            print e


if __name__ == '__main__':

    # test presplitting function
    parser = argparse.ArgumentParser(description='MongoDB pre-splitting tool')

    parser.add_argument('host', action='store', nargs='?', default='localhost:27017', metavar='host:port', help='host:port of mongos or mongod process (default localhost:27017)')
    parser.add_argument('namespace', action='store', help='namespace to shard, in form "database.collection"')
    parser.add_argument('shardkey', action='store', help='shard key to split on, e.g. "_id"')
    parser.add_argument('-n', '--number', action='store', metavar='N', type=int, default=None, help='max. number of shards to use (default is all)')

    parser.add_argument('--verbose', action='store_true', default=False, help='print verbose information')
    args = vars(parser.parse_args())

    args['database'], args['collection'] = args['namespace'].split('.')
    presplit(args['host'], args['database'], args['collection'], args['shardkey'], args['number'])

