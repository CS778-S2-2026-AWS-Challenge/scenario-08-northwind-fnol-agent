#!/bin/sh
set -eu

mongosh --quiet --host mongodb:27017 --eval '
try {
  if (!rs.status().ok) {
    quit(1);
  }
} catch (error) {
  if (error.codeName !== "NotYetInitialized") {
    throw error;
  }
  rs.initiate({ _id: "rs0", members: [{ _id: 0, host: "mongodb:27017" }] });
}
'

until mongosh --quiet 'mongodb://mongodb:27017/?replicaSet=rs0' \
  --eval 'if (!db.hello().isWritablePrimary) quit(1)'
do
  sleep 1
done
