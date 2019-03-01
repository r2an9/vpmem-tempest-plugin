============================
Install VPMEM Tempest Plugin
============================

#. You first need to install Tempest.

#. Install the package from the plugin root directory::

    $ sudo pip install -e .

#. List installed plugin by tempest unity::

    $ tempest list-plugins
    +----------------------+------------------------------------------------+
    |         Name         |                   EntryPoint                   |
    +----------------------+------------------------------------------------+
    | vpmem-tempest-plugin | vpmem_tempest_plugin.plugin:VPMEMTempestPlugin |
    +----------------------+------------------------------------------------+

