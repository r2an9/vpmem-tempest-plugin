# Copyright 2019 Intel Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import libvirt
import time

from lxml import etree
from tempest.common import utils
from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib.common.utils import test_utils
from tempest.lib import decorators
from tempest.lib import exceptions

from vpmem_tempest_plugin.tests.scenario import manager

CONF = config.CONF


class TestServerWithPMEMOps(manager.ScenarioTest):

    """The test suite for server operations with persistent memory.

    This smoke test case follows this basic set of operations:
     * Create a keypair for use in launching an instance
     * Create a security group to control network access in instance
     * Add simple permissive rules to the security group
     * Launch an instance with pmem
     * Perform ssh to instance
     * Verify pmem device in domain xml and by listing the files in vm
     * create, shelve/unshelve, resize, cold migration, live migration
    """

    def setUp(self):
        super(TestServerWithPMEMOps, self).setUp()
        self.run_ssh = CONF.validation.run_validation
        # use custom image for pmem testcases,
        # need to configure CONF.scenario
        self.ssh_user = 'ubuntu'
        self.image = self.glance_image_create()
        self.flavor_1 = self.create_flavor(1024, 1, 10,
                                           extra_spec={'hw:pmem': '4GB'})
        self.flavor_2 = self.create_flavor(1024, 1, 10,
                                           extra_spec={'hw:pmem': '4GB,16GB'})
        self.keypair = self.create_keypair()
        self.security_group = self._create_security_group()

    def _get_bdm(self, source_id, source_type, delete_on_termination=False):
        bd_map_v2 = [{
            'uuid': source_id,
            'source_type': source_type,
            'destination_type': 'volume',
            'boot_index': 0,
            'delete_on_termination': delete_on_termination}]
        return {'block_device_mapping_v2': bd_map_v2}

    def _boot_instance_from_resource(self, source_id,
                                     source_type,
                                     flavor=None,
                                     keypair=None,
                                     security_group=None,
                                     delete_on_termination=False,
                                     name=None):
        create_kwargs = dict()
        if keypair:
            create_kwargs['key_name'] = keypair['name']
        if security_group:
            create_kwargs['security_groups'] = [
                {'name': security_group['name']}]
        create_kwargs.update(self._get_bdm(
            source_id,
            source_type,
            delete_on_termination=delete_on_termination))
        if name:
            create_kwargs['name'] = name
        if flavor:
            create_kwargs['flavor'] = flavor['id']

        return self.create_server(image_id='', **create_kwargs)

    def verify_ssh(self, keypair):
        if self.run_ssh:
            # Obtain a floating IP if floating_ips is enabled
            if (CONF.network_feature_enabled.floating_ips and
                CONF.network.floating_network_name):
                self.ip = self.create_floating_ip(self.instance)['ip']
            else:
                server = self.servers_client.show_server(
                    self.instance['id'])['server']
                self.ip = self.get_server_ip(server)
            # Check ssh
            self.ssh_client = self.get_remote_client(
                ip_address=self.ip,
                username=self.ssh_user,
                private_key=keypair['private_key'],
                server=self.instance)

    def verify_pmem(self, instance, expect_pmem_num):
        # check pmem devices num by listing the pmem device files
        pmem_num = self.ssh_client.exec_command('ls /dev/pmem* | wc -l')
        if int(pmem_num) != expect_pmem_num:
            raise Exception('NVDIMM device num is not as expected.')

    @decorators.idempotent_id('d3b73849-4e71-44a9-b526-a72e35021b0c')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_with_pmem(self):
        self.instance = self.create_server(
            key_name=self.keypair['name'],
            security_groups=[{'name': self.security_group['name']}],
            flavor=self.flavor_1['id'],
            image_id=self.image)
        self.verify_ssh(self.keypair)
        self.verify_pmem(self.instance, 1)

    @decorators.idempotent_id('cb8a99e6-0f6f-11ea-b479-3cfdfecaee70')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_shelve_unshelve_with_pmem(self):
        self.instance = self.create_server(
            key_name=self.keypair['name'],
            security_groups=[{'name': self.security_group['name']}],
            flavor=self.flavor_1['id'],
            image_id=self.image)
        self.verify_ssh(self.keypair)
        self.verify_pmem(self.instance, 1)
        self.servers_client.shelve_server(self.instance['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'SHELVED_OFFLOADED')
        self.servers_client.unshelve_server(self.instance['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        self.verify_pmem(self.instance, 1)

    @decorators.idempotent_id('df50f6ef-425d-4780-9413-54cece5ba8f9')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_resize_with_pmem(self):
        # create instance
        self.instance = self.create_server(
            key_name=self.keypair['name'],
            security_groups=[{'name': self.security_group['name']}],
            flavor=self.flavor_1['id'],
            image_id=self.image)
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        self.verify_ssh(self.keypair)
        self.verify_pmem(self.instance, 1)
        # resize instance
        self.servers_client.resize_server(self.instance['id'],
                                          flavor_ref=self.flavor_2['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'VERIFY_RESIZE')
        # confirm resize
        self.servers_client.confirm_resize_server(self.instance['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        self.verify_pmem(self.instance, 2)

    @decorators.idempotent_id('92f6806e-100e-11ea-b479-3cfdfecaee70')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_cold_migration_with_pmem(self):
        # create instance
        self.instance = self.create_server(
            key_name=self.keypair['name'],
            security_groups=[{'name': self.security_group['name']}],
            flavor=self.flavor_1['id'],
            image_id=self.image)
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        self.verify_ssh(self.keypair)
        self.verify_pmem(self.instance, 1)
        # cold migration
        self.admin_servers_client.migrate_server(self.instance['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'VERIFY_RESIZE')
        self.verify_pmem(self.instance, 1)

    @decorators.idempotent_id('b69002ca-100e-11ea-b479-3cfdfecaee70')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_live_migration_with_pmem(self):
        # create volume
        volume = self.create_volume(size=20, imageRef=self.image)
        self.volumes_client.set_bootable_volume(volume['id'], bootable=True)
        # create instance
        self.instance = self._boot_instance_from_resource(
            flavor=self.flavor_1,
            keypair=self.keypair,
            security_group=self.security_group,
            source_id=volume['id'],
            source_type='volume',
            delete_on_termination=False)
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        self.verify_ssh(self.keypair)
        self.verify_pmem(self.instance, 1)
        # live migration with volume backed
        source_host = self.get_host_for_server(self.instance['id'])
        self.admin_servers_client.live_migrate_server(
                self.instance['id'],
                host=None,
                block_migration=False,
                disk_over_commit=False)
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'ACTIVE')
        destination_host = self.get_host_for_server(self.instance['id'])
        self.verify_pmem(self.instance, 1)
        self.assertNotEqual(source_host, destination_host)
