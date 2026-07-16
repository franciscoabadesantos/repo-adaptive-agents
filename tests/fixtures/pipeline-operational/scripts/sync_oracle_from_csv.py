import oracledb

connection = oracledb.connect()
connection.cursor().execute("insert into target_table values (1)")
