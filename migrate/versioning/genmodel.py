"""
   Code to generate a Python model from a database or differences
   between a model and database.

   Some of this is borrowed heavily from the AutoCode project at:
   http://code.google.com/p/sqlautocode/
"""

import sys
import logging

import migrate
import sqlalchemy


log = logging.getLogger(__name__)
HEADER = """
## File autogenerated by genmodel.py

from sqlalchemy import *
meta = MetaData()
"""

DECLARATIVE_HEADER = """
## File autogenerated by genmodel.py

from sqlalchemy import *
from sqlalchemy.ext import declarative

Base = declarative.declarative_base()
"""


class ModelGenerator(object):

    def __init__(self, diff, declarative=False):
        self.diff = diff
        self.declarative = declarative


    def column_repr(self, col):
        kwarg = []
        if col.key != col.name:
            kwarg.append('key')
        if col.primary_key:
            col.primary_key = True  # otherwise it dumps it as 1
            kwarg.append('primary_key')
        if not col.nullable:
            kwarg.append('nullable')
        if col.onupdate:
            kwarg.append('onupdate')
        if col.default:
            if col.primary_key:
                # I found that PostgreSQL automatically creates a
                # default value for the sequence, but let's not show
                # that.
                pass
            else:
                kwarg.append('default')
        ks = ', '.join('%s=%r' % (k, getattr(col, k)) for k in kwarg)

        # crs: not sure if this is good idea, but it gets rid of extra
        # u''
        name = col.name.encode('utf8')

        type_ = col.type
        for cls in col.type.__class__.__mro__:
            if cls.__module__ == 'sqlalchemy.types' and \
                not cls.__name__.isupper():
                if cls is not type_.__class__:
                    type_ = cls()
                break

        data = {
            'name': name,
            'type': type_,
            'constraints': ', '.join([repr(cn) for cn in col.constraints]),
            'args': ks and ks or ''}

        if data['constraints']:
            if data['args']:
                data['args'] = ',' + data['args']

        if data['constraints'] or data['args']:
            data['maybeComma'] = ','
        else:
            data['maybeComma'] = ''

        commonStuff = """ %(maybeComma)s %(constraints)s %(args)s)""" % data
        commonStuff = commonStuff.strip()
        data['commonStuff'] = commonStuff
        if self.declarative:
            return """%(name)s = Column(%(type)r%(commonStuff)s""" % data
        else:
            return """Column(%(name)r, %(type)r%(commonStuff)s""" % data

    def getTableDefn(self, table):
        out = []
        tableName = table.name
        if self.declarative:
            out.append("class %(table)s(Base):" % {'table': tableName})
            out.append("  __tablename__ = '%(table)s'" % {'table': tableName})
            for col in table.columns:
                out.append("  %s" % self.column_repr(col))
        else:
            out.append("%(table)s = Table('%(table)s', meta," % \
                           {'table': tableName})
            for col in table.columns:
                out.append("  %s," % self.column_repr(col))
            out.append(")")
        return out

    def toPython(self):
        """Assume database is current and model is empty."""
        out = []
        if self.declarative:
            out.append(DECLARATIVE_HEADER)
        else:
            out.append(HEADER)
        out.append("")
        for table in self.diff.tablesMissingInModel:
            out.extend(self.getTableDefn(table))
            out.append("")
        return '\n'.join(out)

    def toUpgradeDowngradePython(self, indent='    '):
        ''' Assume model is most current and database is out-of-date. '''

        decls = ['from migrate.changeset import schema',
                 'meta = MetaData(migrate_engine)']
        for table in self.diff.tablesMissingInModel + \
                self.diff.tablesMissingInDatabase:
            decls.extend(self.getTableDefn(table))

        upgradeCommands, downgradeCommands = [], []
        for table in self.diff.tablesMissingInModel:
            tableName = table.name
            upgradeCommands.append("%(table)s.drop()" % {'table': tableName})
            downgradeCommands.append("%(table)s.create()" % \
                                         {'table': tableName})
        for table in self.diff.tablesMissingInDatabase:
            tableName = table.name
            upgradeCommands.append("%(table)s.create()" % {'table': tableName})
            downgradeCommands.append("%(table)s.drop()" % {'table': tableName})

        for modelTable in self.diff.tablesWithDiff:
            dbTable = self.diff.reflected_model.tables[modelTable.name]
            tableName = modelTable.name
            missingInDatabase, missingInModel, diffDecl = \
                self.diff.colDiffs[tableName]
            for col in missingInDatabase:
                upgradeCommands.append('%s.columns[%r].create()' % (
                        modelTable, col.name))
                downgradeCommands.append('%s.columns[%r].drop()' % (
                        modelTable, col.name))
            for col in missingInModel:
                upgradeCommands.append('%s.columns[%r].drop()' % (
                        modelTable, col.name))
                downgradeCommands.append('%s.columns[%r].create()' % (
                        modelTable, col.name))
            for modelCol, databaseCol, modelDecl, databaseDecl in diffDecl:
                upgradeCommands.append(
                    'assert False, "Can\'t alter columns: %s:%s=>%s"',
                    modelTable, modelCol.name, databaseCol.name)
                downgradeCommands.append(
                    'assert False, "Can\'t alter columns: %s:%s=>%s"',
                    modelTable, modelCol.name, databaseCol.name)
        pre_command = '    meta.bind = migrate_engine'

        return (
            '\n'.join(decls),
            '\n'.join([pre_command] + ['%s%s' % (indent, line) for line in upgradeCommands]),
            '\n'.join([pre_command] + ['%s%s' % (indent, line) for line in downgradeCommands]))

    def applyModel(self):
        """Apply model to current database."""
        # Yuck! We have to import from changeset to apply the
        # monkey-patch to allow column adding/dropping.
        from migrate.changeset import schema

        def dbCanHandleThisChange(missingInDatabase, missingInModel, diffDecl):
            if missingInDatabase and not missingInModel and not diffDecl:
                # Even sqlite can handle this.
                return True
            else:
                return not self.diff.conn.url.drivername.startswith('sqlite')

        meta = sqlalchemy.MetaData(self.diff.conn.engine)

        for table in self.diff.tablesMissingInModel:
            table = table.tometadata(meta)
            table.drop()
        for table in self.diff.tablesMissingInDatabase:
            table = table.tometadata(meta)
            table.create()
        for modelTable in self.diff.tablesWithDiff:
            modelTable = modelTable.tometadata(meta)
            dbTable = self.diff.reflected_model.tables[modelTable.name]
            tableName = modelTable.name
            missingInDatabase, missingInModel, diffDecl = \
                self.diff.colDiffs[tableName]
            if dbCanHandleThisChange(missingInDatabase, missingInModel,
                                     diffDecl):
                for col in missingInDatabase:
                    modelTable.columns[col.name].create()
                for col in missingInModel:
                    dbTable.columns[col.name].drop()
                for modelCol, databaseCol, modelDecl, databaseDecl in diffDecl:
                    databaseCol.alter(modelCol)
            else:
                # Sqlite doesn't support drop column, so you have to
                # do more: create temp table, copy data to it, drop
                # old table, create new table, copy data back.
                #
                # I wonder if this is guaranteed to be unique?
                tempName = '_temp_%s' % modelTable.name

                def getCopyStatement():
                    preparer = self.diff.conn.engine.dialect.preparer
                    commonCols = []
                    for modelCol in modelTable.columns:
                        if modelCol.name in dbTable.columns:
                            commonCols.append(modelCol.name)
                    commonColsStr = ', '.join(commonCols)
                    return 'INSERT INTO %s (%s) SELECT %s FROM %s' % \
                        (tableName, commonColsStr, commonColsStr, tempName)

                # Move the data in one transaction, so that we don't
                # leave the database in a nasty state.
                connection = self.diff.conn.connect()
                trans = connection.begin()
                try:
                    connection.execute(
                        'CREATE TEMPORARY TABLE %s as SELECT * from %s' % \
                            (tempName, modelTable.name))
                    # make sure the drop takes place inside our
                    # transaction with the bind parameter
                    modelTable.drop(bind=connection)
                    modelTable.create(bind=connection)
                    connection.execute(getCopyStatement())
                    connection.execute('DROP TABLE %s' % tempName)
                    trans.commit()
                except:
                    trans.rollback()
                    raise
