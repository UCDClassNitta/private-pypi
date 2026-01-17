#!/usr/bin/env python3
from __future__ import annotations
import argparse
import subprocess
import shutil
import sys
import os
import yaml
from pathlib import Path
from typing import Any

def run(*cmd, cwd=None):
    subprocess.run(cmd, check=True, cwd=cwd)

class WheelhouseBuilder:
    
    def __init__(self, config: dict[str,Any]):
        self.__repos = config['repos']
        self.__clone_dir = Path(config['clone_dir'])
        self.__package_names = [WheelhouseBuilder.package_name_from_repo(repo=repo_name) for repo_name in self.repos]
        self.__existing_versions: dict[str,tuple[str,...]] = dict()
        self.__needed_versions: dict[str,tuple[str,...]] = dict()
        self._make_dirs()
        self._detect_existing()
        
    @property
    def repos(self) -> tuple[str,...]:
        return tuple(self.__repos)
    
    @property
    def clone_dir(self) -> Path:
        return self.__clone_dir
    
    @property
    def package_names(self) -> tuple[str,...]:
        return tuple(self.__package_names)

    @property
    def existing_versions(self) -> dict[str,tuple[str,...]]:
        return self.__existing_versions

    @property
    def needed_versions(self) -> dict[str,tuple[str,...]]:
        return self.__needed_versions

    @staticmethod
    def package_name_from_repo(repo: str) -> str:
        return repo.split('/')[-1]

    @staticmethod
    def repo_owner_and_package_name_from_repo(repo: str) -> tuple[str,str]:
        return repo.split('/')

    @staticmethod
    def pypi_root_directory() -> Path:
        return Path('simple/')

    @staticmethod
    def package_path_from_package_name(package_name: str) -> Path:
        return WheelhouseBuilder.pypi_root_directory() / package_name

    def _make_dirs(self):
        os.makedirs(WheelhouseBuilder.pypi_root_directory(),exist_ok=True)
        for package_name in self.package_names:
            os.makedirs(WheelhouseBuilder.package_path_from_package_name(package_name=package_name),exist_ok=True)
        os.makedirs(f'./{self.clone_dir}',exist_ok=True)

    def _detect_existing(self):
        for package_name in self.package_names:
            package_path = WheelhouseBuilder.package_path_from_package_name(package_name=package_name)
            package_list:list[str] = list()
            for filename in package_path.glob('*.whl'):
                filename_split = filename.name.split('-')
                whl_package = filename_split[0]
                whl_version = filename_split[1]
                if whl_package == package_name:
                    package_list.append(whl_version)
                    if whl_version[0].isdigit():
                        package_list.append(f'v{whl_version}')
            self.__existing_versions[package_name] = tuple(package_list)

    def _clone_repo(self, repo : str):
        repo_owner,package_name = WheelhouseBuilder.repo_owner_and_package_name_from_repo(repo=repo)
        git_clone_path = self.clone_dir / package_name
        if not (git_clone_path / '.git').is_dir():
            run('git', 'clone', f'git@github.com:{repo_owner}/{package_name}.git',cwd=self.clone_dir)
        else:
            run('git', 'checkout', 'main', cwd=git_clone_path)
            run('git', 'pull', cwd=git_clone_path)
            run('git', 'checkout', 'main', cwd=git_clone_path)
        available_versions = self._get_repo_tags(git_clone_path=git_clone_path)
        self.__needed_versions[package_name] = tuple([version for version in available_versions if version not in self.existing_versions[package_name]])
        
    def clone_repos(self):
        for repo in self.repos:
            self._clone_repo(repo=repo)

    #def build_all_versions(self, repo_owner: str, package_name: str):
    def _get_repo_tags(self,git_clone_path: Path) -> list[str]:
        return subprocess.check_output(['git', 'tag', '--sort=v:refname'],
                                       text=True,
                                       cwd=git_clone_path
                                       ).splitlines()
        
    def _build_and_copy_wheels(self, git_clone_path: Path):
        package_name = git_clone_path.name
        for version in self.needed_versions[package_name]:
            run('git', 'checkout', version, cwd=git_clone_path)
            for d in ('dist', 'build'):
                p = git_clone_path / d
                if p.exists():
                    shutil.rmtree(p)
            run('python', '-m', 'build', '--wheel', cwd=git_clone_path)
            for index,ch in enumerate(version):
                if ch.isdigit():
                    break
            built_package_name = package_name.replace('-','_')
            from_path = git_clone_path / f'dist/{built_package_name}-{version[index:]}-py3-none-any.whl'
            run('cp',
                from_path,
                WheelhouseBuilder.package_path_from_package_name(package_name=package_name) / from_path.name)


    def build_all(self):
        for repo in self.repos:
            repo_owner,package_name = WheelhouseBuilder.repo_owner_and_package_name_from_repo(repo=repo)
            git_clone_path = self.clone_dir / package_name
            self._build_and_copy_wheels(git_clone_path=git_clone_path)

    def _create_index(self, package_name: str):
        package_path = WheelhouseBuilder.package_path_from_package_name(package_name=package_name)
        with open(package_path / 'index.html', 'w') as out_file:
            out_file.write('''<!DOCTYPE html>
<html>
  <body>\n''')
            for filename in sorted(package_path.glob('*.whl')):
                filename_split = filename.name.split('-')
                whl_package = filename_split[0]
                whl_version = filename_split[1]
                if whl_package == package_name:
                    out_file.write(f'    <a href="{filename.name}">v{whl_version}</a><br>\n')
            out_file.write('''  </body>
</html>''')

    def create_indices(self):
        with open(WheelhouseBuilder.pypi_root_directory() / 'index.html','w') as out_file:
            out_file.write('''<!DOCTYPE html>
<html>
  <body>\n''')
            for package_name in self.package_names:
                self._create_index(package_name=package_name)
                out_file.write(f'    <a href="{package_name}/">{package_name}</a><br>\n')
            out_file.write('''  </body>
</html>''')
        

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(f'--config', type=str, default='./config.yaml', help='Path to YAML config file')
    args = parser.parse_args(sys.argv[1:])
    config_file_path = Path(args.config)
    config: dict[str,Any] = dict()
    if config_file_path.is_file():
        with config_file_path.open('r', encoding='utf-8') as in_file:
            config = yaml.safe_load(in_file)
    builder = WheelhouseBuilder(config)
    builder.clone_repos()
    builder.build_all()
    builder.create_indices()


if __name__ == '__main__':
    sys.exit(main())
