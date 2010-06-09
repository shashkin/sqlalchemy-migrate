#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
try:
    from runpy import run_module
except ImportError:
    pass #python2.4

from sqlalchemy import MetaData, Table
from nose.plugins.skip import SkipTest

from migrate.versioning.repository import Repository
from migrate.versioning import genmodel, shell, api
from migrate.versioning.exceptions import *
from tests.fixture import Shell, DB, usedb
from tests.fixture import models


class TestShellCommands(Shell):
    """Tests migrate.py commands"""

    def test_help(self):
        """Displays default help dialog"""
        self.assertEqual(self.env.run('bin/migrate -h').returncode, 0)
        self.assertEqual(self.env.run('bin/migrate --help').returncode, 0)
        self.assertEqual(self.env.run('bin/migrate help').returncode, 0)

    def test_help_commands(self):
        """Display help on a specific command"""
        # we can only test that we get some output
        for cmd in api.__all__:
            result = self.env.run('bin/migrate help %s' % cmd)
            self.assertTrue(isinstance(result.stdout, basestring))
            self.assertTrue(result.stdout)
            self.assertFalse(result.stderr)

    def test_shutdown_logging(self):
        """Try to shutdown logging output"""
        repos = self.tmp_repos()
        result = self.env.run('bin/migrate create %s repository_name' % repos)
        result = self.env.run('bin/migrate version %s --disable_logging' % repos)
        self.assertEqual(result.stdout, '')
        result = self.env.run('bin/migrate version %s -q' % repos)
        self.assertEqual(result.stdout, '')

        # TODO: assert logging messages to 0
        shell.main(['version', repos], logging=False)

    def test_main_with_runpy(self):
        if sys.version_info[:2] == (2, 4):
            raise SkipTest("runpy is not part of python2.4")
        try:
            run_module('migrate.versioning.shell', run_name='__main__')
        except:
            pass

    def test_main(self):
        """Test main() function"""
        # TODO: test output?
        repos = self.tmp_repos()
        shell.main(['help'])
        shell.main(['help', 'create'])
        shell.main(['create', 'repo_name', '--preview_sql'], repository=repos)
        shell.main(['version', '--', '--repository=%s' % repos])
        shell.main(['version', '-d', '--repository=%s' % repos, '--version=2'])
        try:
            shell.main(['foobar'])
        except SystemExit, e:
            pass
        try:
            shell.main(['create', 'f', 'o', 'o'])
        except SystemExit, e:
            pass
        try:
            shell.main(['create'])
        except SystemExit, e:
            pass
        try:
            shell.main(['create', 'repo_name'], repository=repos)
        except SystemExit, e:
            pass

    def test_create(self):
        """Repositories are created successfully"""
        repos = self.tmp_repos()

        # Creating a file that doesn't exist should succeed
        result = self.env.run('bin/migrate create %s repository_name' % repos)

        # Files should actually be created
        self.assert_(os.path.exists(repos))

        # The default table should not be None
        repos_ = Repository(repos)
        self.assertNotEquals(repos_.config.get('db_settings', 'version_table'), 'None')

        # Can't create it again: it already exists
        result = self.env.run('bin/migrate create %s repository_name' % repos,
            expect_error=True)
        self.assertEqual(result.returncode, 2)
    
    def test_script(self):
        """We can create a migration script via the command line"""
        repos = self.tmp_repos()
        result = self.env.run('bin/migrate create %s repository_name' % repos)

        result = self.env.run('bin/migrate script --repository=%s Desc' % repos)
        self.assert_(os.path.exists('%s/versions/001_Desc.py' % repos))

        result = self.env.run('bin/migrate script More %s' % repos)
        self.assert_(os.path.exists('%s/versions/002_More.py' % repos))

        result = self.env.run('bin/migrate script "Some Random name" %s' % repos)
        self.assert_(os.path.exists('%s/versions/003_Some_Random_name.py' % repos))

    def test_script_sql(self):
        """We can create a migration sql script via the command line"""
        repos = self.tmp_repos()
        result = self.env.run('bin/migrate create %s repository_name' % repos)

        result = self.env.run('bin/migrate script_sql mydb %s' % repos)
        self.assert_(os.path.exists('%s/versions/001_mydb_upgrade.sql' % repos))
        self.assert_(os.path.exists('%s/versions/001_mydb_downgrade.sql' % repos))

        # Test creating a second
        result = self.env.run('bin/migrate script_sql postgres --repository=%s' % repos)
        self.assert_(os.path.exists('%s/versions/002_postgres_upgrade.sql' % repos))
        self.assert_(os.path.exists('%s/versions/002_postgres_downgrade.sql' % repos))

        # TODO: test --previews

    def test_manage(self):
        """Create a project management script"""
        script = self.tmp_py()
        self.assert_(not os.path.exists(script))

        # No attempt is made to verify correctness of the repository path here
        result = self.env.run('bin/migrate manage %s --repository=/bla/' % script)
        self.assert_(os.path.exists(script))


class TestShellRepository(Shell):
    """Shell commands on an existing repository/python script"""

    def setUp(self):
        """Create repository, python change script"""
        super(TestShellRepository, self).setUp()
        self.path_repos = self.tmp_repos()
        result = self.env.run('bin/migrate create %s repository_name' % self.path_repos)

    def test_version(self):
        """Correctly detect repository version"""
        # Version: 0 (no scripts yet); successful execution
        result = self.env.run('bin/migrate version --repository=%s' % self.path_repos)
        self.assertEqual(result.stdout.strip(), "0")

        # Also works as a positional param
        result = self.env.run('bin/migrate version %s' % self.path_repos)
        self.assertEqual(result.stdout.strip(), "0")

        # Create a script and version should increment
        result = self.env.run('bin/migrate script Desc %s' % self.path_repos)
        result = self.env.run('bin/migrate version %s' % self.path_repos)
        self.assertEqual(result.stdout.strip(), "1")

    def test_source(self):
        """Correctly fetch a script's source"""
        result = self.env.run('bin/migrate script Desc --repository=%s' % self.path_repos)

        filename = '%s/versions/001_Desc.py' % self.path_repos
        source = open(filename).read()
        self.assert_(source.find('def upgrade') >= 0)

        # Version is now 1
        result = self.env.run('bin/migrate version %s' % self.path_repos)
        self.assertEqual(result.stdout.strip(), "1")

        # Output/verify the source of version 1
        result = self.env.run('bin/migrate source 1 --repository=%s' % self.path_repos)
        self.assertEqual(result.stdout.strip(), source.strip())

        # We can also send the source to a file... test that too
        result = self.env.run('bin/migrate source 1 %s --repository=%s' %
            (filename, self.path_repos))
        self.assert_(os.path.exists(filename))
        fd = open(filename)
        result = fd.read()
        self.assert_(result.strip() == source.strip())


class TestShellDatabase(Shell, DB):
    """Commands associated with a particular database"""
    # We'll need to clean up after ourself, since the shell creates its own txn;
    # we need to connect to the DB to see if things worked

    level = DB.CONNECT
        
    @usedb()
    def test_version_control(self):
        """Ensure we can set version control on a database"""
        path_repos = repos = self.tmp_repos()
        url = self.url
        result = self.env.run('bin/migrate create %s repository_name' % repos)

        result = self.env.run('bin/migrate drop_version_control %(url)s %(repos)s'\
            % locals(), expect_error=True)
        self.assertEqual(result.returncode, 1)
        result = self.env.run('bin/migrate version_control %(url)s %(repos)s' % locals())

        # Clean up
        result = self.env.run('bin/migrate drop_version_control %(url)s %(repos)s' % locals())
        # Attempting to drop vc from a database without it should fail
        result = self.env.run('bin/migrate drop_version_control %(url)s %(repos)s'\
            % locals(), expect_error=True)
        self.assertEqual(result.returncode, 1)

    @usedb()
    def test_wrapped_kwargs(self):
        """Commands with default arguments set by manage.py"""
        path_repos = repos = self.tmp_repos()
        url = self.url
        result = self.env.run('bin/migrate create --name=repository_name %s' % repos)
        result = self.env.run('bin/migrate drop_version_control %(url)s %(repos)s' % locals(), expect_error=True)
        self.assertEqual(result.returncode, 1)
        result = self.env.run('bin/migrate version_control %(url)s %(repos)s' % locals())

        result = self.env.run('bin/migrate drop_version_control %(url)s %(repos)s' % locals())

    @usedb()
    def test_version_control_specified(self):
        """Ensure we can set version control to a particular version"""
        path_repos = self.tmp_repos()
        url = self.url
        result = self.env.run('bin/migrate create --name=repository_name %s' % path_repos)
        result = self.env.run('bin/migrate drop_version_control %(url)s %(path_repos)s' % locals(), expect_error=True)
        self.assertEqual(result.returncode, 1)

        # Fill the repository
        path_script = self.tmp_py()
        version = 2
        for i in range(version):
            result = self.env.run('bin/migrate script Desc --repository=%s' % path_repos)

        # Repository version is correct
        result = self.env.run('bin/migrate version %s' % path_repos)
        self.assertEqual(result.stdout.strip(), str(version))

        # Apply versioning to DB
        result = self.env.run('bin/migrate version_control %(url)s %(path_repos)s %(version)s' % locals())

        # Test db version number (should start at 2)
        result = self.env.run('bin/migrate db_version %(url)s %(path_repos)s' % locals())
        self.assertEqual(result.stdout.strip(), str(version))

        # Clean up
        result = self.env.run('bin/migrate drop_version_control %(url)s %(path_repos)s' % locals())

    @usedb()
    def test_upgrade(self):
        """Can upgrade a versioned database"""
        # Create a repository
        repos_name = 'repos_name'
        repos_path = self.tmp()
        result = self.env.run('bin/migrate create %(repos_path)s %(repos_name)s' % locals())
        self.assertEquals(self.run_version(repos_path), 0)

        # Version the DB
        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path), expect_error=True)
        result = self.env.run('bin/migrate version_control %s %s' % (self.url, repos_path))

        # Upgrades with latest version == 0
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        result = self.env.run('bin/migrate upgrade %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        result = self.env.run('bin/migrate upgrade %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        result = self.env.run('bin/migrate upgrade %s %s 1' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 1)
        result = self.env.run('bin/migrate upgrade %s %s -1' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 2)

        # Add a script to the repository; upgrade the db
        result = self.env.run('bin/migrate script Desc --repository=%s' % (repos_path))
        self.assertEquals(self.run_version(repos_path), 1)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        # Test preview
        result = self.env.run('bin/migrate upgrade %s %s 0 --preview_sql' % (self.url, repos_path))
        result = self.env.run('bin/migrate upgrade %s %s 0 --preview_py' % (self.url, repos_path))

        result = self.env.run('bin/migrate upgrade %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 1)
        
        # Downgrade must have a valid version specified
        result = self.env.run('bin/migrate downgrade %s %s' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 2)
        result = self.env.run('bin/migrate downgrade %s %s -1' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 2)
        result = self.env.run('bin/migrate downgrade %s %s 2' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 2)
        self.assertEquals(self.run_db_version(self.url, repos_path), 1)
        
        result = self.env.run('bin/migrate downgrade %s %s 0' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        
        result = self.env.run('bin/migrate downgrade %s %s 1' % (self.url, repos_path), expect_error=True)
        self.assertEquals(result.returncode, 2)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path))

    def _run_test_sqlfile(self, upgrade_script, downgrade_script):
        # TODO: add test script that checks if db really changed
        repos_path = self.tmp()
        repos_name = 'repos'

        result = self.env.run('bin/migrate create %s %s' % (repos_path, repos_name))
        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path), expect_error=True)
        result = self.env.run('bin/migrate version_control %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_version(repos_path), 0)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        beforeCount = len(os.listdir(os.path.join(repos_path, 'versions')))  # hmm, this number changes sometimes based on running from svn
        result = self.env.run('bin/migrate script_sql %s --repository=%s' % ('postgres', repos_path))
        self.assertEquals(self.run_version(repos_path), 1)
        self.assertEquals(len(os.listdir(os.path.join(repos_path, 'versions'))), beforeCount + 2)

        open('%s/versions/001_postgres_upgrade.sql' % repos_path, 'a').write(upgrade_script)
        open('%s/versions/001_postgres_downgrade.sql' % repos_path, 'a').write(downgrade_script)

        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        self.assertRaises(Exception, self.engine.text('select * from t_table').execute)

        result = self.env.run('bin/migrate upgrade %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 1)
        self.engine.text('select * from t_table').execute()

        result = self.env.run('bin/migrate downgrade %s %s 0' % (self.url, repos_path))
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        self.assertRaises(Exception, self.engine.text('select * from t_table').execute)

    # The tests below are written with some postgres syntax, but the stuff
    # being tested (.sql files) ought to work with any db. 
    @usedb(supported='postgres')
    def test_sqlfile(self):
        upgrade_script = """
        create table t_table (
            id serial,
            primary key(id)
        );
        """
        downgrade_script = """
        drop table t_table;
        """
        self.meta.drop_all()
        self._run_test_sqlfile(upgrade_script, downgrade_script)
        
    @usedb(supported='postgres')
    def test_sqlfile_comment(self):
        upgrade_script = """
        -- Comments in SQL break postgres autocommit
        create table t_table (
            id serial,
            primary key(id)
        );
        """
        downgrade_script = """
        -- Comments in SQL break postgres autocommit
        drop table t_table;
        """
        self._run_test_sqlfile(upgrade_script, downgrade_script)

    @usedb()
    def test_command_test(self):
        repos_name = 'repos_name'
        repos_path = self.tmp()

        result = self.env.run('bin/migrate create repository_name --repository=%s' % repos_path)
        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path), expect_error=True)
        result = self.env.run('bin/migrate version_control %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_version(repos_path), 0)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        # Empty script should succeed
        result = self.env.run('bin/migrate script Desc %s' % repos_path)
        result = self.env.run('bin/migrate test %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_version(repos_path), 1)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        # Error script should fail
        script_path = self.tmp_py()
        script_text='''
        from sqlalchemy import *
        from migrate import *
        
        def upgrade():
            print 'fgsfds'
            raise Exception()
        
        def downgrade():
            print 'sdfsgf'
            raise Exception()
        '''.replace("\n        ", "\n")
        file = open(script_path, 'w')
        file.write(script_text)
        file.close()

        result = self.env.run('bin/migrate test %s %s bla' % (self.url, repos_path), expect_error=True)
        self.assertEqual(result.returncode, 2)
        self.assertEquals(self.run_version(repos_path), 1)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        # Nonempty script using migrate_engine should succeed
        script_path = self.tmp_py()
        script_text = '''
        from sqlalchemy import *
        from migrate import *

        from migrate.changeset import schema
        
        meta = MetaData(migrate_engine)
        account = Table('account', meta,
            Column('id', Integer, primary_key=True),
            Column('login', Text),
            Column('passwd', Text),
        )
        def upgrade():
            # Upgrade operations go here. Don't create your own engine; use the engine
            # named 'migrate_engine' imported from migrate.
            meta.create_all()
        
        def downgrade():
            # Operations to reverse the above upgrade go here.
            meta.drop_all()
        '''.replace("\n        ", "\n")
        file = open(script_path, 'w')
        file.write(script_text)
        file.close()
        result = self.env.run('bin/migrate test %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_version(repos_path), 1)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)
        
    @usedb()
    def test_rundiffs_in_shell(self):
        # This is a variant of the test_schemadiff tests but run through the shell level.
        # These shell tests are hard to debug (since they keep forking processes), so they shouldn't replace the lower-level tests.
        repos_name = 'repos_name'
        repos_path = self.tmp()
        script_path = self.tmp_py()
        model_module = 'tests.fixture.models:meta_rundiffs'
        old_model_module = 'tests.fixture.models:meta_old_rundiffs'

        # Create empty repository.
        self.meta = MetaData(self.engine, reflect=True)
        self.meta.reflect()
        self.meta.drop_all()  # in case junk tables are lying around in the test database

        result = self.env.run('bin/migrate create %s %s' % (repos_path, repos_name))
        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path), expect_error=True)
        result = self.env.run('bin/migrate version_control %s %s' % (self.url, repos_path))
        self.assertEquals(self.run_version(repos_path), 0)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)

        # Setup helper script.
        result = self.env.run('bin/migrate manage %s --repository=%s --url=%s --model=%s'\
            % (script_path, repos_path, self.url, model_module))
        self.assert_(os.path.exists(script_path))

        # Model is defined but database is empty.
        result = self.env.run('bin/migrate compare_model_to_db %s %s --model=%s' \
            % (self.url, repos_path, model_module))
        self.assert_("tables missing in database: tmp_account_rundiffs" in result.stdout)

        # Test Deprecation
        result = self.env.run('bin/migrate compare_model_to_db %s %s --model=%s' \
            % (self.url, repos_path, model_module.replace(":", ".")), expect_error=True)
        self.assertEqual(result.returncode, 0)
        self.assertTrue("DeprecationWarning" in result.stderr)
        self.assert_("tables missing in database: tmp_account_rundiffs" in result.stdout)

        # Update db to latest model.
        result = self.env.run('bin/migrate update_db_from_model %s %s %s'\
            % (self.url, repos_path, model_module))
        self.assertEquals(self.run_version(repos_path), 0)
        self.assertEquals(self.run_db_version(self.url, repos_path), 0)  # version did not get bumped yet because new version not yet created

        result = self.env.run('bin/migrate compare_model_to_db %s %s %s'\
            % (self.url, repos_path, model_module))
        self.assert_("No schema diffs" in result.stdout)

        result = self.env.run('bin/migrate drop_version_control %s %s' % (self.url, repos_path), expect_error=True)
        result = self.env.run('bin/migrate version_control %s %s' % (self.url, repos_path))

        result = self.env.run('bin/migrate create_model %s %s' % (self.url, repos_path))
        temp_dict = dict()
        exec result.stdout in temp_dict

        # TODO: compare whole table
        self.compare_columns_equal(models.tmp_account_rundiffs.c, temp_dict['tmp_account_rundiffs'].c)
        #self.assertTrue("""tmp_account_rundiffs = Table('tmp_account_rundiffs', meta,
  #Column('id', Integer(),  primary_key=True, nullable=False),
  #Column('login', String(length=None, convert_unicode=False, assert_unicode=None)),
  #Column('passwd', String(length=None, convert_unicode=False, assert_unicode=None))""" in result.stdout)

        # We're happy with db changes, make first db upgrade script to go from version 0 -> 1.
        result = self.env.run('bin/migrate make_update_script_for_model', expect_error=True)
        self.assertTrue('Not enough arguments' in result.stderr)

        result_script = self.env.run('bin/migrate make_update_script_for_model %s %s %s %s'\
            % (self.url, repos_path, old_model_module, model_module))
        self.assertEqualsIgnoreWhitespace(result_script.stdout,
        '''from sqlalchemy import *
        from migrate import *

        from migrate.changeset import schema

        meta = MetaData()
        tmp_account_rundiffs = Table('tmp_account_rundiffs', meta,
          Column('id', Integer(),  primary_key=True, nullable=False),
          Column('login', String(length=None, convert_unicode=False, assert_unicode=None)),
          Column('passwd', String(length=None, convert_unicode=False, assert_unicode=None)),
        )

        def upgrade(migrate_engine):
            # Upgrade operations go here. Don't create your own engine; bind migrate_engine
            # to your metadata
            meta.bind = migrate_engine
            tmp_account_rundiffs.create()

        def downgrade(migrate_engine):
            # Operations to reverse the above upgrade go here.
            meta.bind = migrate_engine
            tmp_account_rundiffs.drop()''')
    
        # Save the upgrade script.
        result = self.env.run('bin/migrate script Desc %s' % repos_path)
        upgrade_script_path = '%s/versions/001_Desc.py' % repos_path
        open(upgrade_script_path, 'w').write(result_script.stdout)

        result = self.env.run('bin/migrate compare_model_to_db %s %s %s'\
            % (self.url, repos_path, model_module))
        self.assert_("No schema diffs" in result.stdout)

        self.meta.drop_all()  # in case junk tables are lying around in the test database
