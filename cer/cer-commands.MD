##List IP Subnets:

```
run sql select subnet.ipaddress, subnet.subnetmask, erl.name from ceripsubnet subnet, cererl erl where subnet.fkerl = erl.erlid

Alternative Table (Discovered/Discovered-Only Subnets)If you are looking for subnets that CER has actively discovered via connected IP phones (rather than static configurations manually defined by an administrator), query the unlocated or dynamically tracked view:

```
run sql select ipaddress, subnetmask, fkerl from cerunlocatedphone



To find IP subnets where the assigned ERL name contains a specific string, you can modify the SQL query to use the LIKE operator along with wildcard characters (%).

run sql select subnet.ipaddress, subnet.subnetmask, erl.name from ceripsubnet subnet, cererl erl where subnet.fkerl = erl.erlid and erl.name like '%YOUR_SEARCH_TEXT%'


Delete Subnet:
DELETE https://{CER-IP}/cerappservices/service//ipsubnetphone/delete
{ "ipsubnet": "10.17.36.20" }


List ERLs:
run sql select erlid, name from cererl


List ERLs with details:
run sql select erlid, name from cererl order by name asc

List ERLs containing:
Log in to your CER command line interface and execute the following command, making sure to swap out YOUR_SEARCH_TEXT with the word or code you want to match:

run sql select erlid, name from cererl where name like '%YOUR_SEARCH_TEXT%'


Delete ERL:
DELETE https://{CER-IP}/cerappservices/service/cerl?erlName=YOUR_ERL_NAME


List all On-site Security Contacts:To see a clean list of all configured security IDs, names, and contact details, use:

run sql select onsitealertid, name, emailid, pageremailid from ceronsitealert


List ERLs and their assigned Security Personnel:To find out which physical locations are mapped to which security handlers, join the ERL and on-site alert tables:

run sql select erl.name, alert.name from cererl erl, ceronsitealert alert where erl.fkonsitealert = alert.onsitealertid


DELETING ALERTS:

While deleting data directly using SQL is highly discouraged due to data integrity risks, you can technically force-delete an on-site alert contact from the database using the run sql delete command, provided you first sever its relationships with any active Emergency Response Locations (ERLs).If you attempt to delete a contact that is actively mapped to an ERL, the Informix database engine will throw a foreign key constraint violation error and block the transaction.

Step 1: Clear the Mappings on Active ERLsBefore purging the alert contact, you must find out which ERLs are using it and clear the association.Find the onsitealertid of the contact you want to delete:sql

run sql select onsitealertid, name from ceronsitealert

Identify blocking ERLs using that ID (replace X with your target ID):sql

run sql select erlid, name from cererl where fkonsitealert = X

Nullify the relationship so the ERLs no longer reference that alert ID:sql

run sql update cererl set fkonsitealert = null where fkonsitealert = X

Step 2: Delete the Contact RecordOnce no ERLs are referencing the ID, execute the final delete statement to wipe it completely from the system configuration:sql

run sql delete from ceronsitealert where onsitealertid = X
