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
     * Verify pmem device in domain xml
     * Terminate the instance
    """

    def setUp(self):
        super(TestServerWithPMEMOps, self).setUp()
        self.run_ssh = CONF.validation.run_validation
        self.ssh_user = CONF.validation.image_ssh_user

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
        conn = libvirt.open('qemu+ssh://root@localhost/system')
        pmem_num = 0
        for domain in conn.listAllDomains():
            if domain.UUIDString() != instance['id']:
                continue
            xmldoc = etree.fromstring(domain.XMLDesc())
            for c in xmldoc.getchildren():
                if c.tag == 'devices':
                    for d in c.getchildren():
                        if d.tag == 'memory' and d.get('model') == 'nvdimm':
                            pmem_num += 1
            break
        conn.close()
        if pmem_num != expect_pmem_num:
            raise Exception('NVDIMM device num is not as expected.')

    @decorators.idempotent_id('d3b73849-4e71-44a9-b526-a72e35021b0c')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_with_pmem(self):
        flavor = self.create_flavor(2048, 4, 10, name='test_flavor',
                                    extra_spec={'hw:pmem': '4GB'})
        keypair = self.create_keypair()
        security_group = self._create_security_group()
        self.instance = self.create_server(
            key_name=keypair['name'],
            security_groups=[{'name': security_group['name']}],
            flavor=flavor['id'],
            image_id=CONF.compute.image_ref)
        self.verify_ssh(keypair)
        self.verify_pmem(self.instance, 1)

    @decorators.idempotent_id('df50f6ef-425d-4780-9413-54cece5ba8f9')
    @decorators.attr(type='smoke')
    @utils.services('compute', 'network')
    def test_server_resize_with_pmem(self):
        flavor_1 = self.create_flavor(2048, 4, 10,
                                      extra_spec={'hw:pmem': '4GB'})
        flavor_2 = self.create_flavor(2048, 4, 10,
                                      extra_spec={'hw:pmem': '4GB,16GB'})
        keypair = self.create_keypair()
        security_group = self._create_security_group()
        self.instance = self.create_server(
            key_name=keypair['name'],
            security_groups=[{'name': security_group['name']}],
            flavor=flavor_1['id'],
            image_id=CONF.compute.image_ref)
        self.verify_pmem(self.instance, 1)
        self.servers_client.resize_server(self.instance['id'],
                                          flavor_ref=flavor_2['id'])
        waiters.wait_for_server_status(self.servers_client,
                                       self.instance['id'],
                                       'VERIFY_RESIZE')
        #from remote_pdb import RemotePdb
        #RemotePdb('127.0.0.1', 4444).set_trace()
        self.servers_client.confirm_resize_server(self.instance['id'])
        self.verify_pmem(self.instance, 2)
