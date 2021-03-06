
import datetime

import pytest
from unittest.case import SkipTest

from s3tests_pytest.tests import (
    TestBaseClass, parse_xml_to_json,
    ClientError, assert_raises,
    nuke_prefixed_buckets, get_buckets_list,
    get_client, get_alt_client,
    get_bad_auth_client, get_unauthenticated_client
)


class TestBucketBase(TestBaseClass):

    @staticmethod
    def bucket_is_empty(bucket) -> bool:
        is_empty = True
        for _ in bucket.objects.all():
            is_empty = False
            break
        return is_empty

    @staticmethod
    def get_prefixes(response):
        """
        return lists of strings that are prefixes from a client.list_objects() response
        """
        prefixes = []
        if 'CommonPrefixes' in response:
            prefix_list = response['CommonPrefixes']
            prefixes = [prefix['Prefix'] for prefix in prefix_list]
        return prefixes

    def validate_bucket_list(self, client, bucket_name, prefix, delimiter, marker, max_keys,
                             is_truncated, check_objs, check_prefixes, next_marker):
        response = client.list_objects(
            Bucket=bucket_name, Delimiter=delimiter, Marker=marker, MaxKeys=max_keys, Prefix=prefix)
        self.eq(response['IsTruncated'], is_truncated)
        if 'NextMarker' not in response:
            response['NextMarker'] = None
        self.eq(response['NextMarker'], next_marker)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)

        self.eq(len(keys), len(check_objs))
        self.eq(len(prefixes), len(check_prefixes))
        self.eq(keys, check_objs)
        self.eq(prefixes, check_prefixes)

        return response['NextMarker']

    def validate_bucket_list_v2(self, client, bucket_name, prefix, delimiter, continuation_token, max_keys,
                                is_truncated, check_objs, check_prefixes, last=False):

        params = dict(Bucket=bucket_name, Delimiter=delimiter, MaxKeys=max_keys, Prefix=prefix)
        if continuation_token is not None:
            params['ContinuationToken'] = continuation_token
        else:
            params['StartAfter'] = ''
        response = client.list_objects_v2(**params)
        self.eq(response['IsTruncated'], is_truncated)
        if 'NextContinuationToken' not in response:
            response['NextContinuationToken'] = None
        if last:
            self.eq(response['NextContinuationToken'], None)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)

        self.eq(len(keys), len(check_objs))
        self.eq(len(prefixes), len(check_prefixes))
        self.eq(keys, check_objs)
        self.eq(prefixes, check_prefixes)

        return response['NextContinuationToken']

    def check_bad_bucket_name(self, config, bucket_name):
        """
        Attempt to create a bucket with a specified name, and confirm
        that the request fails because of an invalid bucket name.
        """
        client = get_client(config)
        e = assert_raises(ClientError, client.create_bucket, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    def check_invalid_bucket_name(self, config, invalid_name):
        """
        Send a create bucket_request with an invalid bucket name
        that will bypass the ParamValidationError that would be raised
        if the invalid bucket name that was passed in normally.
        This function returns the status and error code from the failure
        """
        client = get_client(config)
        valid_bucket_name = self.get_new_bucket_name(config)

        def replace_bucket_name_from_url(**kwargs):
            url = kwargs['params']['url']
            new_url = url.replace(valid_bucket_name, invalid_name)
            kwargs['params']['url'] = new_url

        client.meta.events.register('before-call.s3.CreateBucket', replace_bucket_name_from_url)
        e = assert_raises(ClientError, client.create_bucket, Bucket=invalid_name)
        status, error_code = self.get_status_and_error_code(e.response)
        return status, error_code

    def check_good_bucket_name(self, config, name, prefix=None):
        """
        Attempt to create a bucket with a specified name
        and (specified or default) prefix, returning the
        results of that effort.
        """
        # tests using this with the default prefix must *not* rely on
        # being able to set the initial character, or exceed the max len

        # tests using this with a custom prefix are responsible for doing
        # their own setup/teardown nukes, with their custom prefix; this
        # should be very rare
        client = get_client(config)
        if prefix is None:
            prefix = config.bucket_prefix

        bucket_name = '{prefix}{name}'.format(
            prefix=prefix,
            name=name,
            client=client
        )
        response = client.create_bucket(Bucket=bucket_name)
        self.eq(response['ResponseMetadata']['HTTPStatusCode'], 200)

    def bucket_create_naming_good_long(self, config, length):
        """
        Attempt to create a bucket whose name (including the
        prefix) is of a specified length.
        """
        # tests using this with the default prefix must *not* rely on
        # being able to set the initial character, or exceed the max len

        # tests using this with a custom prefix are responsible for doing
        # their own setup/teardown nukes, with their custom prefix; this
        # should be very rare
        prefix = self.get_new_bucket_name(config)

        # assert len(prefix) < 63
        # num = length - len(prefix)
        # name = num * 'a'

        name = (63 - len(prefix)) * 'a' if len(prefix) <= 63 else ''
        bucket_name = '{prefix}{name}'.format(
            prefix=prefix,
            name=name,
        )
        bucket_name = bucket_name[:length]

        client = get_client(config)
        response = client.create_bucket(Bucket=bucket_name)
        self.eq(response['ResponseMetadata']['HTTPStatusCode'], 200)


class TestBucketOpts(TestBucketBase):

    @pytest.mark.ess
    def test_bucket_list_empty(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????????????????no contents
        """
        bucket = self.get_new_bucket_resource(s3cfg_global_unique)
        is_empty = self.bucket_is_empty(bucket)

        self.eq(is_empty, True)

    @pytest.mark.ess
    def test_bucket_list_distinct(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????????????????????????????????????????contents
        """
        bucket1 = self.get_new_bucket_resource(s3cfg_global_unique)
        bucket2 = self.get_new_bucket_resource(s3cfg_global_unique)
        bucket1.put_object(Body='str', Key='asdf')

        is_empty1 = self.bucket_is_empty(bucket1)
        is_empty2 = self.bucket_is_empty(bucket2)

        self.eq(is_empty1, False)
        self.eq(is_empty2, True)

    @pytest.mark.ess
    def test_bucket_list_many(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???MaxKeys???Marker??????
        """
        keys_in = ['foo', 'bar', 'baz']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, MaxKeys=2)
        keys = self.get_keys(response)
        self.eq(len(keys), 2)
        self.eq(keys, ['bar', 'baz'])
        self.eq(response['IsTruncated'], True)

        response = client.list_objects(Bucket=bucket_name, Marker='baz', MaxKeys=2)
        keys = self.get_keys(response)
        self.eq(len(keys), 1)
        self.eq(response['IsTruncated'], False)
        self.eq(keys, ['foo'])

    @pytest.mark.ess
    def test_bucket_list_v2_many(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???MaxKeys???StartAfter??????
        """
        keys_in = ['foo', 'bar', 'baz']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=2)
        keys = self.get_keys(response)
        self.eq(len(keys), 2)
        self.eq(keys, ['bar', 'baz'])
        self.eq(response['IsTruncated'], True)

        response = client.list_objects_v2(Bucket=bucket_name, StartAfter='baz', MaxKeys=2)
        keys = self.get_keys(response)
        self.eq(len(keys), 1)
        self.eq(response['IsTruncated'], False)
        self.eq(keys, ['foo'])

    @pytest.mark.ess
    def test_basic_key_count(self, s3cfg_global_unique):
        """
        ??????-??????list_objects_v2??????
        """
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        client = get_client(s3cfg_global_unique)
        client.create_bucket(Bucket=bucket_name)
        for i in range(5):
            client.put_object(Bucket=bucket_name, Key=str(i))
        resp = client.list_objects_v2(Bucket=bucket_name)

        # KeyCount is the number of keys returned with this request.
        # KeyCount will always be less than or equals to MaxKeys field.
        # Say you ask for 50 keys, your result will include less than equals 50 keys
        self.eq(resp['KeyCount'], 5)

    @pytest.mark.ess
    def test_bucket_list_delimiter_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???Delimiter??????
        """
        keys_in = ['foo/bar', 'foo/bar/xyzzy', 'quux/thud', 'asdf']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='/')
        self.eq(response['Delimiter'], '/')
        keys = self.get_keys(response)
        self.eq(keys, ['asdf'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        self.eq(prefixes, ['foo/', 'quux/'])

    @pytest.mark.ess
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(
        reason="KeyCount=len(CommonPrefixes)+len(Contents), and Ceph is not suitable.", run=True, strict=True)
    def test_bucket_list_v2_delimiter_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???Delimiter?????????
        KeyCount=len(CommonPrefixes)+len(Contents), ceph??????????????????
        """
        # https://docs.aws.amazon.com/zh_cn/AmazonS3/latest/API/API_ListObjectsV2.html#AmazonS3-ListObjectsV2-response-KeyCount
        # Sample Request: Listing keys using the prefix and delimiter parameters
        keys_in = ['foo/bar', 'foo/bar/xyzzy', 'quux/thud', 'asdf']

        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='/')
        self.eq(response['Delimiter'], '/')
        keys = self.get_keys(response)
        self.eq(keys, ['asdf'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        self.eq(prefixes, ['foo/', 'quux/'])
        # 1 != 3
        self.eq(response['KeyCount'], len(prefixes) + len(keys))

    @pytest.mark.ess
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="??????????????????????????????url??????", run=True, strict=True)
    def test_bucket_list_v2_encoding_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???Delimiter???EncodingType??????
        """
        keys_in = ['foo+1/bar', 'foo/bar/xyzzy', 'quux ab/thud', 'asdf+b']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        # EncodingType: Encoding type used by Amazon S3 to encode object keys in the response.
        # Delimiter: A delimiter is a character you use to group keys.
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='/', EncodingType='url')
        self.eq(response['Delimiter'], '/')
        keys = self.get_keys(response)
        self.eq(keys, ['asdf%2Bb'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 3)

        # ['foo+1/', 'foo/', 'quux ab/'] != ['foo%2B1/', 'foo/', 'quux%20ab/']
        self.eq(prefixes, ['foo%2B1/', 'foo/', 'quux%20ab/'])

    @pytest.mark.ess
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="??????????????????????????????url??????", run=True, strict=True)
    def test_bucket_list_encoding_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???Delimiter???EncodingType??????
        """
        keys_in = ['foo+1/bar', 'foo/bar/xyzzy', 'quux ab/thud', 'asdf+b']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='/', EncodingType='url')
        self.eq(response['Delimiter'], '/')
        keys = self.get_keys(response)
        self.eq(keys, ['asdf%2Bb'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 3)

        # ['foo+1/', 'foo/', 'quux ab/'] != ['foo%2B1/', 'foo/', 'quux%20ab/']
        self.eq(prefixes, ['foo%2B1/', 'foo/', 'quux%20ab/'])

    @pytest.mark.ess
    def test_bucket_list_delimiter_prefix(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???Delimiter???Marker???MaxKeys???Prefix????????????
        """
        client = get_client(s3cfg_global_unique)

        keys_in = ['asdf', 'boo/bar', 'boo/baz/xyzzy', 'cquux/thud', 'cquux/bla']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        delim = '/'
        prefix = ''

        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 1, True, ['asdf'], [], 'asdf'
        )
        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, True, [], ['boo/'], 'boo/'
        )
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, False, [], ['cquux/'], None
        )

        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 2, True, ['asdf'], ['boo/'], 'boo/'
        )
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 2, False, [], ['cquux/'], None
        )

        prefix = 'boo/'

        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 1, True, ['boo/bar'], [], 'boo/bar'
        )
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, False, [], ['boo/baz/'], None
        )

        self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 2, False, ['boo/bar'], ['boo/baz/'], None
        )

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_prefix(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???Delimiter???Marker???MaxKeys???Prefix????????????
        """
        client = get_client(s3cfg_global_unique)

        keys_in = ['asdf', 'boo/bar', 'boo/baz/xyzzy', 'cquux/thud', 'cquux/bla']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        delim = '/'
        prefix = ''

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 1, True, ['asdf'], [])
        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, True, [], ['boo/'])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, False, [], ['cquux/'], last=True)

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 2, True, ['asdf'], ['boo/'])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 2, False, [], ['cquux/'], last=True)

        prefix = 'boo/'

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 1, True, ['boo/bar'], [])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, False, [], ['boo/baz/'], last=True)

        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 2, False, ['boo/bar'], ['boo/baz/'], last=True)

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_prefix_ends_with_delimiter(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???prefix and delimiter handling when object ends with delimiter
        """
        client = get_client(s3cfg_global_unique)

        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=['asdf/'])
        self.validate_bucket_list_v2(
            client, bucket_name, 'asdf/', '/', None, 1000, False, ['asdf/'], [], last=True)

    @pytest.mark.ess
    def test_bucket_list_delimiter_prefix_ends_with_delimiter(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???prefix and delimiter handling when object ends with delimiter
        """
        client = get_client(s3cfg_global_unique)

        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=['asdf/'])
        self.validate_bucket_list(
            client, bucket_name, 'asdf/', '/', '', 1000, False, ['asdf/'], [], None)

    @pytest.mark.ess
    def test_bucket_list_delimiter_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???non_slash_delimiter_characters
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='a')
        self.eq(response['Delimiter'], 'a')

        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        # bar, baz, and cab should be broken up by the 'a' delimiters
        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        self.eq(prefixes, ['ba', 'ca'])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???non_slash_delimiter_characters
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='a')
        self.eq(response['Delimiter'], 'a')

        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        # bar, baz, and cab should be broken up by the 'a' delimiters
        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        self.eq(prefixes, ['ba', 'ca'])

    @pytest.mark.ess
    def test_bucket_list_delimiter_prefix_underscore(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???prefixes_starting_with_underscore
        """
        client = get_client(s3cfg_global_unique)

        keys_in = ['_obj1_', '_under1/bar', '_under1/baz/xyzzy', '_under2/thud', '_under2/bla']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        delim = '/'
        prefix = ''
        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 1, True, ['_obj1_'], [], '_obj1_')
        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, True, [], ['_under1/'], '_under1/')
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, False, [], ['_under2/'], None)

        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 2, True, ['_obj1_'], ['_under1/'], '_under1/')
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 2, False, [], ['_under2/'], None)

        prefix = '_under1/'

        marker = self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 1, True, ['_under1/bar'], [], '_under1/bar')
        self.validate_bucket_list(
            client, bucket_name, prefix, delim, marker, 1, False, [], ['_under1/baz/'], None)

        self.validate_bucket_list(
            client, bucket_name, prefix, delim, '', 2, False, ['_under1/bar'], ['_under1/baz/'], None)

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_prefix_underscore(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???prefixes_starting_with_underscore
        """
        client = get_client(s3cfg_global_unique)

        keys_in = ['_obj1_', '_under1/bar', '_under1/baz/xyzzy', '_under2/thud', '_under2/bla']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        delim = '/'
        prefix = ''

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 1, True, ['_obj1_'], [])
        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, True, [], ['_under1/'])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, False, [], ['_under2/'], last=True)

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 2, True, ['_obj1_'], ['_under1/'])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 2, False, [], ['_under2/'], last=True)

        prefix = '_under1/'

        continuation_token = self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 1, True, ['_under1/bar'], [])
        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, continuation_token, 1, False, [], ['_under1/baz/'], last=True)

        self.validate_bucket_list_v2(
            client, bucket_name, prefix, delim, None, 2, False, ['_under1/bar'], ['_under1/baz/'], last=True)

    @pytest.mark.ess
    def test_bucket_list_delimiter_percentage(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???percentage_delimiter_characters
        """
        keys_in = ['b%ar', 'b%az', 'c%ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='%')
        self.eq(response['Delimiter'], '%')
        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b%', 'c%'])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_percentage(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???percentage_delimiter_characters
        """
        keys_in = ['b%ar', 'b%az', 'c%ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='%')
        self.eq(response['Delimiter'], '%')

        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b%', 'c%'])

    @pytest.mark.ess
    def test_bucket_list_delimiter_whitespace(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???whitespace_delimiter_characters
        """
        keys_in = ['b ar', 'b az', 'c ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter=' ')
        self.eq(response['Delimiter'], ' ')
        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b ', 'c '])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_whitespace(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???whitespace_delimiter_characters
        """
        keys_in = ['b ar', 'b az', 'c ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter=' ')
        self.eq(response['Delimiter'], ' ')
        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b ', 'c '])

    @pytest.mark.ess
    def test_bucket_list_delimiter_dot(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???dot_delimiter_characters
        """
        keys_in = ['b.ar', 'b.az', 'c.ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='.')
        self.eq(response['Delimiter'], '.')
        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b.', 'c.'])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_dot(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???dot_delimiter_characters
        """
        keys_in = ['b.ar', 'b.az', 'c.ab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='.')
        self.eq(response['Delimiter'], '.')
        keys = self.get_keys(response)
        # foo contains no 'a' and so is a complete key
        self.eq(keys, ['foo'])

        prefixes = self.get_prefixes(response)
        self.eq(len(prefixes), 2)
        # bar, baz, and cab should be broken up by the 'a' delimiters
        self.eq(prefixes, ['b.', 'c.'])

    @pytest.mark.ess
    def test_bucket_list_delimiter_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???non_printable_delimiter_can_be_specified
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='\x0a')
        self.eq(response['Delimiter'], '\x0a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???non_printable_delimiter_can_be_specified
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='\x0a')
        self.eq(response['Delimiter'], '\x0a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_delimiter_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???empty_delimiter_can_be_specified
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='')
        # putting an empty value into Delimiter will not return a value in the response
        self.eq('Delimiter' in response, False)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???empty_delimiter_can_be_specified
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='')
        # putting an empty value into Delimiter will not return a value in the response
        self.eq('Delimiter' in response, False)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_delimiter_none(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???unspecified_delimiter_defaults_to_none
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name)
        # putting an empty value into Delimiter will not return a value in the response
        self.eq('Delimiter' in response, False)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_none(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???unspecified_delimiter_defaults_to_none
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name)
        # putting an empty value into Delimiter will not return a value in the response
        self.eq('Delimiter' in response, False)

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_fetch_owner_not_empty(self, s3cfg_global_unique):
        """
        ??????-??????list_objects_v2???FetchOwner is True
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, FetchOwner=True)
        objs_list = response['Contents']
        self.eq('Owner' in objs_list[0], True)

    @pytest.mark.ess
    def test_bucket_list_v2_fetch_owner_default_empty(self, s3cfg_global_unique):
        """
        ??????-??????list_objects_v2???FetchOwner ?????????False???
        The owner field is not present in listV2 by default,
        if you want to return owner field with each key in the result then set the fetch owner field to true.
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name)
        objs_list = response['Contents']
        self.eq('Owner' in objs_list[0], False)

    @pytest.mark.ess
    def test_bucket_list_v2_fetch_owner_empty(self, s3cfg_global_unique):
        """
        ??????-??????list_objects_v2???FetchOwner ?????????False
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, FetchOwner=False)
        objs_list = response['Contents']
        self.eq('Owner' in objs_list[0], False)

    @pytest.mark.ess
    def test_bucket_list_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???unused_delimiter_is_not_found
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='/')
        # putting an empty value into Delimiter will not return a value in the response
        self.eq(response['Delimiter'], '/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???unused_delimiter_is_not_found
        """
        keys_in = ['bar', 'baz', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='/')
        # putting an empty value into Delimiter will not return a value in the response
        self.eq(response['Delimiter'], '/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_delimiter_not_skip_special(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???delimiter_not_skip_special_keys
        """
        keys_in = ['0/'] + ['0/%s' % i for i in range(1000, 1999)]
        keys_in2 = ['1999', '1999#', '1999+', '2000']
        keys_in += keys_in2
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in, threads=10)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='/')
        self.eq(response['Delimiter'], '/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in2)
        self.eq(prefixes, ['0/'])

    @pytest.mark.ess
    def test_bucket_list_prefix_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???Prefix??????
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='foo/')
        self.eq(response['Prefix'], 'foo/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['foo/bar', 'foo/baz'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_basic(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???Prefix??????
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='foo/')
        self.eq(response['Prefix'], 'foo/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['foo/bar', 'foo/baz'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Prefix???
        just testing that we can do the delimiter and prefix logic on non-slashes
        """
        keys_in = ['bar', 'baz', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='ba')
        self.eq(response['Prefix'], 'ba')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['bar', 'baz'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???Prefix???
        just testing that we can do the delimiter and prefix logic on non-slashes
        """
        keys_in = ['bar', 'baz', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='ba')
        self.eq(response['Prefix'], 'ba')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['bar', 'baz'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Prefix???empty_prefix_returns_everything
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='')
        self.eq(response['Prefix'], '')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???Prefix???empty_prefix_returns_everything
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='')
        self.eq(response['Prefix'], '')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_none(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Prefix???unspecified_prefix_returns_everything
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='')
        self.eq(response['Prefix'], '')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_none(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???Prefix???unspecified_prefix_returns_everything
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='')
        self.eq(response['Prefix'], '')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, keys_in)
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Prefix???nonexistent_prefix_returns_nothing
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='d')
        self.eq(response['Prefix'], 'd')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???Prefix???nonexistent_prefix_returns_nothing
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='d')
        self.eq(response['Prefix'], 'd')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Prefix???non_printable_prefix_can_be_specified
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Prefix='\x0a')
        self.eq(response['Prefix'], '\x0a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Prefix???non_printable_prefix_can_be_specified
        """
        keys_in = ['foo/bar', 'foo/baz', 'quux']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Prefix='\x0a')
        self.eq(response['Prefix'], '\x0a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_delimiter_basic(self, s3cfg_global_unique):
        """
        ??????-??????list-object???Delimiter???Prefix???returns_only_objects_directly_under_prefix
        """
        keys_in = ['foo/bar', 'foo/baz/xyzzy', 'quux/thud', 'asdf']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='/', Prefix='foo/')
        self.eq(response['Prefix'], 'foo/')
        self.eq(response['Delimiter'], '/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['foo/bar'])
        self.eq(prefixes, ['foo/baz/'])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_delimiter_basic(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Delimiter???Prefix???returns_only_objects_directly_under_prefix
        """
        keys_in = ['foo/bar', 'foo/baz/xyzzy', 'quux/thud', 'asdf']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='/', Prefix='foo/')
        self.eq(response['Prefix'], 'foo/')
        self.eq(response['Delimiter'], '/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['foo/bar'])
        self.eq(prefixes, ['foo/baz/'])

    @pytest.mark.ess
    def test_bucket_list_prefix_delimiter_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-object???Delimiter???Prefix???non_slash_delimiters
        """
        keys_in = ['bar', 'bazar', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='a', Prefix='ba')
        self.eq(response['Prefix'], 'ba')
        self.eq(response['Delimiter'], 'a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['bar'])
        self.eq(prefixes, ['baza'])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_delimiter_alt(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Delimiter???Prefix???non_slash_delimiters
        """
        keys_in = ['bar', 'bazar', 'cab', 'foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='a', Prefix='ba')
        self.eq(response['Prefix'], 'ba')
        self.eq(response['Delimiter'], 'a')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['bar'])
        self.eq(prefixes, ['baza'])

    @pytest.mark.ess
    def test_bucket_list_prefix_delimiter_prefix_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object???Delimiter???Prefix??????????????????finds_nothing_unmatched_prefix
        """
        keys_in = ['b/a/r', 'b/a/c', 'b/a/g', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='d', Prefix='/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_delimiter_prefix_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Delimiter???Prefix??????????????????finds_nothing_unmatched_prefix
        """
        keys_in = ['b/a/r', 'b/a/c', 'b/a/g', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='d', Prefix='/')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_delimiter_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object???Delimiter??????????????????Prefix???overridden slash ceases to be a delimiter
        """
        keys_in = ['b/a/c', 'b/a/g', 'b/a/r', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='z', Prefix='b')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['b/a/c', 'b/a/g', 'b/a/r'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_delimiter_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Delimiter??????????????????Prefix???overridden slash ceases to be a delimiter
        """
        keys_in = ['b/a/c', 'b/a/g', 'b/a/r', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='z', Prefix='b')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, ['b/a/c', 'b/a/g', 'b/a/r'])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_prefix_delimiter_prefix_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object???Delimiter??????????????????Prefix??????????????????
        finds_nothing_unmatched_prefix_and_delimiter
        """
        keys_in = ['b/a/c', 'b/a/g', 'b/a/r', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Delimiter='z', Prefix='y')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_v2_prefix_delimiter_prefix_delimiter_not_exist(self, s3cfg_global_unique):
        """
        ??????-??????list-object-v2???Delimiter??????????????????Prefix??????????????????
        finds_nothing_unmatched_prefix_and_delimiter
        """
        keys_in = ['b/a/c', 'b/a/g', 'b/a/r', 'g']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, Delimiter='z', Prefix='y')

        keys = self.get_keys(response)
        prefixes = self.get_prefixes(response)
        self.eq(keys, [])
        self.eq(prefixes, [])

    @pytest.mark.ess
    def test_bucket_list_max_keys_one(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???MaxKeys=1???Marker?????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, MaxKeys=1)
        self.eq(response['IsTruncated'], True)

        keys = self.get_keys(response)
        self.eq(keys, keys_in[0:1])
        # Marker is where you want Amazon S3 to start listing from.
        # Amazon S3 starts listing after this specified key.
        # Marker can be any key in the bucket.
        response = client.list_objects(Bucket=bucket_name, Marker=keys_in[0])
        self.eq(response['IsTruncated'], False)

        keys = self.get_keys(response)
        self.eq(keys, keys_in[1:])

    @pytest.mark.ess
    def test_bucket_list_v2_max_keys_one(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???MaxKeys=1???Marker?????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
        self.eq(response['IsTruncated'], True)

        keys = self.get_keys(response)
        self.eq(keys, keys_in[0:1])
        # StartAfter is same to Marker in list-objects interface.
        response = client.list_objects_v2(Bucket=bucket_name, StartAfter=keys_in[0])
        self.eq(response['IsTruncated'], False)

        keys = self.get_keys(response)
        self.eq(keys, keys_in[1:])

    @pytest.mark.ess
    def test_bucket_list_max_keys_zero(self, s3cfg_global_unique):
        """
        ??????-??????list_objects???MaxKeys=0
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, MaxKeys=0)

        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, [])

    @pytest.mark.ess
    def test_bucket_list_v2_max_keys_zero(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2???MaxKeys=0
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=0)

        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, [])

    @pytest.mark.ess
    def test_bucket_list_max_keys_none(self, s3cfg_global_unique):
        """
        ??????-??????list_objects????????????MaxKeys???
        Sets the maximum number of keys returned in the response.
        By default the action returns up to 1,000 key names.
        The response might contain fewer keys but will never contain more.
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name)
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)
        self.eq(response['MaxKeys'], 1000)

    @pytest.mark.ess
    def test_bucket_list_v2_max_keys_none(self, s3cfg_global_unique):
        """
        ??????-??????list_objects-v2????????????MaxKeys???
        Sets the maximum number of keys returned in the response.
        By default the action returns up to 1,000 key names.
        The response might contain fewer keys but will never contain more.
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name)
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)
        self.eq(response['MaxKeys'], 1000)

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="Ceph?????????????????????Quota????????????????????????????????????", run=True, strict=True)
    def test_account_usage(self, s3cfg_global_unique):
        """
        ??????-????????????url??????????usage???????????????????????????account???usage
        """
        # boto3.set_stream_logger(name='botocore')

        client = get_client(s3cfg_global_unique)

        # adds the unordered query parameter
        def add_usage(**kwargs):
            kwargs['params']['url'] += "?usage"

        http_response_body = None

        def get_http_response_body(**kwargs):
            nonlocal http_response_body
            # botocore -> awsrequest.py -> AWSResponse

            # http_response_body = kwargs['http_response'].__dict__['_content']
            http_response_body = kwargs['http_response'].content

        client.meta.events.register('before-call.s3.ListBuckets', add_usage)
        client.meta.events.register('after-call.s3.ListBuckets', get_http_response_body)
        client.list_buckets()
        xml = self.ele_tree.fromstring(http_response_body.decode('utf-8'))
        parsed = parse_xml_to_json(xml)
        summary = parsed['Summary']
        from pprint import pprint
        pprint(summary)
        """
         'Summary': {'Stats': {'TotalBytes': '515376377461',
                               'TotalBytesRounded': '515379904512',
                               'TotalEntries': '2987'},
                     'User': {'Total': {'BytesReceived': '1475',
                                        'BytesSent': '749838',
                                        'Ops': '1719',
                                        'SuccessfulOps': '1474'},
                              'User': 'wanghx',
                              'categories': {'Entry': {'BytesReceived': '0',
                                                       'BytesSent': '0',
                                                       'Category': 'stat_bucket',
                                                       'Ops': '30',
                                                       'SuccessfulOps': '9'}}}}}
        """
        self.eq(summary['QuotaMaxBytes'], '-1')
        self.eq(summary['QuotaMaxBuckets'], '1000')
        self.eq(summary['QuotaMaxObjCount'], '-1')
        self.eq(summary['QuotaMaxBytesPerBucket'], '-1')
        self.eq(summary['QuotaMaxObjCountPerBucket'], '-1')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="Ceph?????????????????????Quota????????????????????????????????????", run=True, strict=True)
    def test_head_bucket_usage(self, s3cfg_global_unique):
        """
        ??????-??????bucket usage?????????head-bucket???headers?????????quota????????????
        """
        # boto3.set_stream_logger(name='botocore')
        client = get_client(s3cfg_global_unique)
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=['foo'])

        http_response = None

        def get_http_response(**kwargs):
            nonlocal http_response
            http_response = kwargs['http_response'].__dict__

        # adds the unordered query parameter
        client.meta.events.register('after-call.s3.HeadBucket', get_http_response)
        client.head_bucket(Bucket=bucket_name)
        _headers = http_response['headers']
        """
        {'X-RGW-Object-Count': '1', 
        'X-RGW-Bytes-Used': '3', 
        'x-amz-request-id': 'tx00000000000000001a790-0062562a50-39e502-zone-1647582137', 
        'Content-Length': '0', 
        'Date': 'Wed, 13 Apr 2022 01:41:36 GMT', 
        'Connection': 'Keep-Alive'}
        """
        self.eq(_headers['X-RGW-Object-Count'], '1')
        self.eq(_headers['X-RGW-Bytes-Used'], '3')
        self.eq(_headers['X-RGW-Quota-User-Size'], '-1')
        self.eq(_headers['X-RGW-Quota-User-Objects'], '-1')
        self.eq(_headers['X-RGW-Quota-Max-Buckets'], '1000')
        self.eq(_headers['X-RGW-Quota-Bucket-Size'], '-1')
        self.eq(_headers['X-RGW-Quota-Bucket-Objects'], '-1')

    @pytest.mark.ess
    def test_bucket_list_unordered(self, s3cfg_global_unique):
        """
        ??????-??????list-objects?????????allow-unordered=true
        """
        # boto3.set_stream_logger(name='botocore')
        keys_in = ['ado', 'bot', 'cob', 'dog', 'emu', 'fez', 'gnu', 'hex',
                   'abc/ink', 'abc/jet', 'abc/kin', 'abc/lax', 'abc/mux',
                   'def/nim', 'def/owl', 'def/pie', 'def/qed', 'def/rye',
                   'ghi/sew', 'ghi/tor', 'ghi/uke', 'ghi/via', 'ghi/wit',
                   'xix', 'yak', 'zoo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)

        # adds the unordered query parameter
        def add_unordered(**kwargs):
            kwargs['params']['url'] += "&allow-unordered=true"

        client.meta.events.register('before-call.s3.ListObjects', add_unordered)

        # test simple retrieval
        response = client.list_objects(Bucket=bucket_name, MaxKeys=1000)
        unordered_keys_out = self.get_keys(response)
        self.eq(len(keys_in), len(unordered_keys_out))
        self.eq(keys_in.sort(), unordered_keys_out.sort())

        # test retrieval with prefix
        response = client.list_objects(Bucket=bucket_name,
                                       MaxKeys=1000,
                                       Prefix="abc/")
        unordered_keys_out = self.get_keys(response)
        self.eq(5, len(unordered_keys_out))

        # test incremental retrieval with marker
        response = client.list_objects(Bucket=bucket_name, MaxKeys=6)
        unordered_keys_out = self.get_keys(response)
        self.eq(6, len(unordered_keys_out))

        # now get the next bunch
        response = client.list_objects(Bucket=bucket_name,
                                       MaxKeys=6,
                                       Marker=unordered_keys_out[-1])
        unordered_keys_out2 = self.get_keys(response)
        self.eq(6, len(unordered_keys_out2))

        # make sure there's no overlap between the incremental retrievals
        intersect = set(unordered_keys_out).intersection(unordered_keys_out2)
        self.eq(0, len(intersect))

        # verify that unordered used with delimiter results in error
        e = assert_raises(ClientError, client.list_objects, Bucket=bucket_name, Delimiter="/")
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidArgument')

    @pytest.mark.ess
    def test_bucket_list_v2_unordered(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2?????????allow-unordered=true
        """
        # boto3.set_stream_logger(name='botocore')
        keys_in = ['ado', 'bot', 'cob', 'dog', 'emu', 'fez', 'gnu', 'hex',
                   'abc/ink', 'abc/jet', 'abc/kin', 'abc/lax', 'abc/mux',
                   'def/nim', 'def/owl', 'def/pie', 'def/qed', 'def/rye',
                   'ghi/sew', 'ghi/tor', 'ghi/uke', 'ghi/via', 'ghi/wit',
                   'xix', 'yak', 'zoo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        # adds the unordered query parameter
        def add_unordered(**kwargs):
            kwargs['params']['url'] += "&allow-unordered=true"

        client.meta.events.register('before-call.s3.ListObjects', add_unordered)

        # test simple retrieval
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=1000)
        unordered_keys_out = self.get_keys(response)
        self.eq(len(keys_in), len(unordered_keys_out))
        self.eq(keys_in.sort(), unordered_keys_out.sort())

        # test retrieval with prefix
        response = client.list_objects_v2(Bucket=bucket_name,
                                          MaxKeys=1000,
                                          Prefix="abc/")
        unordered_keys_out = self.get_keys(response)
        self.eq(5, len(unordered_keys_out))

        # test incremental retrieval with marker
        response = client.list_objects_v2(Bucket=bucket_name, MaxKeys=6)
        unordered_keys_out = self.get_keys(response)
        self.eq(6, len(unordered_keys_out))

        # now get the next bunch
        response = client.list_objects_v2(Bucket=bucket_name,
                                          MaxKeys=6,
                                          StartAfter=unordered_keys_out[-1])
        unordered_keys_out2 = self.get_keys(response)
        self.eq(6, len(unordered_keys_out2))

        # make sure there's no overlap between the incremental retrievals
        intersect = set(unordered_keys_out).intersection(unordered_keys_out2)
        self.eq(0, len(intersect))

        # verify that unordered used with delimiter results in error
        e = assert_raises(ClientError,
                          client.list_objects, Bucket=bucket_name, Delimiter="/")
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidArgument')

    @pytest.mark.ess
    def test_bucket_list_max_keys_invalid(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???url???????????????max-keys??????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)

        # adds invalid max keys to url
        # before list_objects is called
        def add_invalid_max_keys(**kwargs):
            kwargs['params']['url'] += "&max-keys=blah"

        client.meta.events.register('before-call.s3.ListObjects', add_invalid_max_keys)

        e = assert_raises(ClientError, client.list_objects, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidArgument')

    @pytest.mark.ess
    def test_bucket_list_marker_none(self, s3cfg_global_unique):
        """
        ??????-??????list-objects??????????????????Marker??????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response = client.list_objects(Bucket=bucket_name)
        self.eq(response['Marker'], '')

    @pytest.mark.ess
    def test_bucket_list_marker_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Marker???????????????????????????????????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response = client.list_objects(Bucket=bucket_name, Marker='')
        self.eq(response['Marker'], '')
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)

    @pytest.mark.ess
    def test_bucket_list_v2_continuation_token_empty(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???ContinuationToken??????????????????????????????????????????????????????
        ContinuationToken indicates Amazon S3 that the list is being continued on this bucket with a token.
        ContinuationToken is obfuscated and is not a real key.
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response = client.list_objects_v2(Bucket=bucket_name, ContinuationToken='')
        self.eq(response['ContinuationToken'], '')
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)

    @pytest.mark.ess
    def test_bucket_list_v2_continuation_token(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???ContinuationToken?????????NextContinuationToken???????????????????????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response1 = client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
        next_continuation_token = response1['NextContinuationToken']

        response2 = client.list_objects_v2(Bucket=bucket_name, ContinuationToken=next_continuation_token)
        self.eq(response2['ContinuationToken'], next_continuation_token)
        self.eq(response2['IsTruncated'], False)
        keys_in2 = ['baz', 'foo', 'quxx']
        keys = self.get_keys(response2)
        self.eq(keys, keys_in2)

    @pytest.mark.ess
    def test_bucket_list_v2_both_continuation_token_start_after(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???StartAfter????????????????????????MaxKeys???1??????
        ContinuationToken?????????NextContinuationToken???????????????????????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response1 = client.list_objects_v2(Bucket=bucket_name, StartAfter='bar', MaxKeys=1)
        next_continuation_token = response1['NextContinuationToken']

        response2 = client.list_objects_v2(Bucket=bucket_name,
                                           StartAfter='bar',
                                           ContinuationToken=next_continuation_token)
        self.eq(response2['ContinuationToken'], next_continuation_token)
        self.eq(response2['StartAfter'], 'bar')
        self.eq(response2['IsTruncated'], False)
        keys_in2 = ['foo', 'quxx']
        keys = self.get_keys(response2)
        self.eq(keys, keys_in2)

    @pytest.mark.ess
    def test_bucket_list_marker_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Marker???????????? \x0a
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response = client.list_objects(Bucket=bucket_name, Marker='\x0a')
        print(response)
        print(response['Marker'])
        """
        'EncodingType': 'url',
        'IsTruncated': False,
        'Marker': '\n',  # <--- maybe translated to \n by print function
        'MaxKeys': 1000,
        'Name': 'ess-din8lrxq0x23f6xyxsqk4kgxq-1',
        'Prefix': '',
        """
        self.eq(response['Marker'], '\x0a')
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)

    @pytest.mark.ess
    def test_bucket_list_v2_start_after_unreadable(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???Marker???????????? \x0a
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)
        client = get_client(s3cfg_global_unique)

        response = client.list_objects_v2(Bucket=bucket_name, StartAfter='\x0a')
        self.eq(response['StartAfter'], '\x0a')
        self.eq(response['IsTruncated'], False)
        keys = self.get_keys(response)
        self.eq(keys, keys_in)

    @pytest.mark.ess
    def test_bucket_list_marker_not_in_list(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Marker????????????b?????????????????????????????????????????????
        ????????????????????????b???????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Marker='blah')
        self.eq(response['Marker'], 'blah')
        keys = self.get_keys(response)
        self.eq(keys, ['foo', 'quxx'])

    @pytest.mark.ess
    def test_bucket_list_v2_start_after_not_in_list(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???StartAfter????????????b?????????????????????????????????????????????
        ????????????????????????b???????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, StartAfter='blah')
        self.eq(response['StartAfter'], 'blah')
        keys = self.get_keys(response)
        self.eq(keys, ['foo', 'quxx'])

    @pytest.mark.ess
    def test_bucket_list_marker_after_list(self, s3cfg_global_unique):
        """
        ??????-??????list-objects???Marker????????????zzz???????????????????????????
        ?????????????????????????????????????????????zzz????????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects(Bucket=bucket_name, Marker='zzz')
        self.eq(response['Marker'], 'zzz')
        keys = self.get_keys(response)
        self.eq(response['IsTruncated'], False)
        self.eq(keys, [])

    @pytest.mark.ess
    def test_bucket_list_v2_start_after_after_list(self, s3cfg_global_unique):
        """
        ??????-??????list-objects-v2???StartAfter????????????zzz???????????????????????????
        ?????????????????????????????????????????????zzz????????????????????????
        """
        keys_in = ['bar', 'baz', 'foo', 'quxx']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        client = get_client(s3cfg_global_unique)
        response = client.list_objects_v2(Bucket=bucket_name, StartAfter='zzz')
        self.eq(response['StartAfter'], 'zzz')
        keys = self.get_keys(response)
        self.eq(response['IsTruncated'], False)
        self.eq(keys, [])

    @pytest.mark.ess
    def test_bucket_list_objects_anonymous_fail(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????list-objects?????????
        403??? AccessDenied
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)

        unauthenticated_client = get_unauthenticated_client(s3cfg_global_unique)
        e = assert_raises(ClientError, unauthenticated_client.list_objects, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 403)
        self.eq(error_code, 'AccessDenied')

    @pytest.mark.ess
    def test_bucket_list_v2_objects_anonymous_fail(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????list-objects-v2?????????
        403??? AccessDenied
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)

        unauthenticated_client = get_unauthenticated_client(s3cfg_global_unique)
        e = assert_raises(ClientError, unauthenticated_client.list_objects_v2, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 403)
        self.eq(error_code, 'AccessDenied')

    @pytest.mark.ess
    def test_bucket_not_exist(self, s3cfg_global_unique):
        """
        ??????-?????????????????????Bucket??????list-objects?????????
        404??? NoSuchBucket
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        e = assert_raises(ClientError, client.list_objects, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 404)
        self.eq(error_code, 'NoSuchBucket')

    @pytest.mark.ess
    def test_bucket_v2_not_exist(self, s3cfg_global_unique):
        """
        ??????-?????????????????????Bucket??????list-objects?????????
        404??? NoSuchBucket
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        e = assert_raises(ClientError, client.list_objects_v2, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 404)
        self.eq(error_code, 'NoSuchBucket')

    @pytest.mark.ess
    def test_bucket_delete_not_exist(self, s3cfg_global_unique):
        """
        ??????-?????????????????????Bucket??????delete-bucket?????????
        404??? NoSuchBucket
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        e = assert_raises(ClientError, client.delete_bucket, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 404)
        self.eq(error_code, 'NoSuchBucket')

    @pytest.mark.ess
    def test_bucket_delete_nonempty(self, s3cfg_global_unique):
        """
        ??????-???????????????Bucket??????delete-bucket?????????
        409??? BucketNotEmpty
        """
        client = get_client(s3cfg_global_unique)

        keys_in = ['foo']
        bucket_name = self.create_objects(config=s3cfg_global_unique, keys=keys_in)

        e = assert_raises(ClientError, client.delete_bucket, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 409)
        self.eq(error_code, 'BucketNotEmpty')

    @pytest.mark.ess
    def test_bucket_create_delete(self, s3cfg_global_unique):
        """
        ??????-??????????????????Bucket??????delete-bucket?????????
        404??? NoSuchBucket
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)
        client.delete_bucket(Bucket=bucket_name)  # delete this bucket

        e = assert_raises(ClientError, client.delete_bucket, Bucket=bucket_name)  # raise Error
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 404)
        self.eq(error_code, 'NoSuchBucket')

    @pytest.mark.ess
    def test_bucket_head(self, s3cfg_global_unique):
        """
        ??????-??????????????????bucket??????head-bucket??????
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)

        response = client.head_bucket(Bucket=bucket_name)
        self.eq(response['ResponseMetadata']['HTTPStatusCode'], 200)

    @pytest.mark.ess
    def test_bucket_head_not_exist(self, s3cfg_global_unique):
        """
        ??????-?????????????????????bucket??????head-bucket?????????
        404???Not Found
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        e = assert_raises(ClientError, client.head_bucket, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 404)
        # n.b., RGW does not send a response document for this operation,
        # which seems consistent with https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html

    @pytest.mark.ess
    def test_bucket_head_extended(self, s3cfg_global_unique):
        """
        ??????-??????head-bucket????????????headers????????????
        """
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)

        response = client.head_bucket(Bucket=bucket_name)
        self.eq(int(response['ResponseMetadata']['HTTPHeaders']['x-rgw-object-count']), 0)
        self.eq(int(response['ResponseMetadata']['HTTPHeaders']['x-rgw-bytes-used']), 0)

        self.create_objects(s3cfg_global_unique, bucket_name=bucket_name, keys=['foo', 'bar', 'baz'])
        response = client.head_bucket(Bucket=bucket_name)

        self.eq(int(response['ResponseMetadata']['HTTPHeaders']['x-rgw-object-count']), 3)
        self.eq(int(response['ResponseMetadata']['HTTPHeaders']['x-rgw-bytes-used']), 9)

    @pytest.mark.ess
    def test_bucket_create_exists(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????????????????????????????
        ??????????????????????????????region??????????????????
        """
        # aws-s3 default region allows recreation of buckets
        # but all other regions fail with BucketAlreadyOwnedByYou.
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        client.create_bucket(Bucket=bucket_name)
        try:
            client.create_bucket(Bucket=bucket_name)
        except ClientError as e:
            status, error_code = self.get_status_and_error_code(e.response)
            self.eq(status, 409)
            self.eq(error_code, 'BucketAlreadyOwnedByYou')

    @pytest.mark.ess
    def test_bucket_get_location(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????LocationConstraint,
        Ceph??????zonegroup????????????????????????radosgw-admin zonegroup list?????????
        """
        location_constraint = s3cfg_global_unique.main_api_name
        if not location_constraint:
            raise SkipTest

        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        # Specifies the Region where the bucket will be created.
        # If you don't specify a Region, the bucket is created in the US East (N. Virginia) Region (us-east-1).

        # In Ceph, LocationConstraint is zonegroup
        # you can use [radosgw-admin zonegroup list] command to list those group.
        client.create_bucket(
            Bucket=bucket_name, CreateBucketConfiguration={'LocationConstraint': location_constraint})

        response = client.get_bucket_location(Bucket=bucket_name)
        if location_constraint == "":
            location_constraint = None
        self.eq(response['LocationConstraint'], location_constraint)

    @pytest.mark.ess
    def test_bucket_create_exists_non_owner(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????????????????
        409???BucketAlreadyExists
        """
        # Names are shared across a global namespace. As such, no two
        # users can create a bucket with that same name.
        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)

        alt_client = get_alt_client(s3cfg_global_unique)

        client.create_bucket(Bucket=bucket_name)
        e = assert_raises(ClientError, alt_client.create_bucket, Bucket=bucket_name)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 409)
        self.eq(error_code, 'BucketAlreadyExists')

    @pytest.mark.ess_maybe
    def test_logging_toggle(self, s3cfg_global_unique):
        """
        (operation='set/enable/disable logging target')
        (assertion='operations succeed')
        """
        # TODO rgw log_bucket.set_as_logging_target() gives 403 Forbidden
        # http://tracker.newdream.net/issues/984

        client = get_client(s3cfg_global_unique)
        bucket_name = self.get_new_bucket(client, s3cfg_global_unique)

        main_display_name = s3cfg_global_unique.main_display_name
        main_user_id = s3cfg_global_unique.main_user_id

        status = {'LoggingEnabled': {'TargetBucket': bucket_name, 'TargetGrants': [
            {'Grantee': {'DisplayName': main_display_name, 'ID': main_user_id, 'Type': 'CanonicalUser'},
             'Permission': 'FULL_CONTROL'}], 'TargetPrefix': 'foologgingprefix'}}

        client.put_bucket_logging(Bucket=bucket_name, BucketLoggingStatus=status)
        client.get_bucket_logging(Bucket=bucket_name)
        status = {'LoggingEnabled': {}}
        client.put_bucket_logging(Bucket=bucket_name, BucketLoggingStatus=status)
        # NOTE: this does not actually test whether or not logging works

    @pytest.mark.ess
    def test_buckets_create_then_list(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????
        """
        client = get_client(s3cfg_global_unique)
        prefix = s3cfg_global_unique.bucket_prefix

        bucket_names = []
        for i in range(5):
            bucket_name = self.get_new_bucket_name(s3cfg_global_unique)
            bucket_names.append(bucket_name)

        for name in bucket_names:
            client.create_bucket(Bucket=name)

        buckets_list = get_buckets_list(client, prefix)

        for name in bucket_names:
            if name not in buckets_list:
                raise RuntimeError(
                    "S3 implementation's GET on Service did not return bucket we created: %r", name)

    @pytest.mark.ess
    def test_buckets_list_ctime(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????????????????????????????????????????CreationDate
        """
        # check that creation times are within a day
        before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        client = get_client(s3cfg_global_unique)

        buckets = [self.get_new_bucket_name(s3cfg_global_unique) for _ in range(5)]
        for bucket_name in buckets:
            client.create_bucket(Bucket=bucket_name)

        response = client.list_buckets()
        for bucket in response['Buckets']:
            if bucket['Name'] in buckets:
                ctime = bucket['CreationDate']
                assert before <= ctime

    @pytest.mark.ess
    def test_list_buckets_anonymous(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????list-buckets?????????????????????????????????0
        """
        # Get a connection with bad authorization, then change it to be our new Anonymous auth mechanism,
        # emulating standard HTTP access.

        # While it may have been possible to use httplib directly, doing it this way takes care of also
        # allowing us to vary the calling format in testing.
        unauthenticated_client = get_unauthenticated_client(s3cfg_global_unique)
        response = unauthenticated_client.list_buckets()
        self.eq(len(response['Buckets']), 0)

    @pytest.mark.ess
    def test_list_buckets_invalid_auth(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????????????????
        403??? InvalidAccessKeyId
        """
        bad_auth_client = get_bad_auth_client(s3cfg_global_unique)
        e = assert_raises(ClientError, bad_auth_client.list_buckets)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 403)
        self.eq(error_code, 'InvalidAccessKeyId')

    @pytest.mark.ess
    def test_list_buckets_bad_auth(self, s3cfg_global_unique):
        """
        ??????-???????????????sk??????????????????????????????????????????
        403???SignatureDoesNotMatch
        """
        main_access_key = s3cfg_global_unique.main_access_key
        bad_auth_client = get_bad_auth_client(s3cfg_global_unique, aws_access_key_id=main_access_key)

        e = assert_raises(ClientError, bad_auth_client.list_buckets)
        status, error_code = self.get_status_and_error_code(e.response)
        self.eq(status, 403)
        self.eq(error_code, 'SignatureDoesNotMatch')

    @pytest.mark.ess
    def test_bucket_recreate_not_overriding(self, s3cfg_global_unique):
        """
        ??????-??????create bucket with objects and recreate it???
        bucket recreation not overriding index
        """
        key_names = ['mykey1', 'mykey2']
        bucket_name = self.create_objects(s3cfg_global_unique, keys=key_names)

        client = get_client(s3cfg_global_unique)
        objs_list = self.get_objects_list(client=client, bucket=bucket_name)
        self.eq(key_names, objs_list)

        client.create_bucket(Bucket=bucket_name)

        objs_list = self.get_objects_list(client=client, bucket=bucket_name)
        self.eq(key_names, objs_list)

    @pytest.mark.ess
    def test_bucket_list_special_prefix(self, s3cfg_global_unique):
        """
        ??????-??????create and list objects with underscore as prefix, list using prefix
        """
        client = get_client(s3cfg_global_unique)

        key_names = ['_bla/1', '_bla/2', '_bla/3', '_bla/4', 'abcd']
        bucket_name = self.create_objects(s3cfg_global_unique, keys=key_names)

        objs_list = self.get_objects_list(client=client, bucket=bucket_name)
        self.eq(len(objs_list), 5)

        objs_list = self.get_objects_list(client=client, bucket=bucket_name, prefix='_bla/')
        self.eq(len(objs_list), 4)


class TestBucketNameRules(TestBucketBase):
    """
    https://docs.aws.amazon.com/zh_cn/zh_cn/AmazonS3/latest/userguide/bucketnamingrules.html
    ???????????????????????? Amazon S3 ?????????????????????
    1. ??????????????????????????? 3??????????????? 63??????????????????????????????
    2. ?????????????????????????????????????????????????????? (.) ???????????? (-) ?????????
    3. ?????????????????????????????????????????????????????????
    4. ??????????????????????????? IP ????????????????????????192.168.5.4??????
    5. ?????????????????????????????? xn-- ?????????
    6. ?????????????????????????????? -s3alias ???????????????????????????????????????????????????
        ???????????????????????????????????????????????????????????????????????????
    7. ????????????????????????????????? AWS ?????????????????? AWS ??????????????????????????????
        ????????????????????????AWS ????????????????????????aws?????????????????????aws-cn????????????????????? aws-us-gov???AWS GovCloud (US) ????????????
    8. ??????????????????????????????????????????????????? AWS ??????????????????????????????????????????
    9. ??? Amazon S3 Transfer Acceleration ???????????????????????????????????????????????? (.)???
        ?????? Transfer Acceleration ????????????????????????????????? Amazon S3 Transfer Acceleration ???????????????????????????????????????
    10. ???????????????????????????????????????????????????????????????????????????????????? (.)??????????????????????????????????????????????????????
        ???????????????????????????????????????????????????????????? HTTPS ?????????????????????????????????????????????????????????????????????
        ??????????????????????????????????????????????????????????????????????????????????????????????????????
    11. ???????????????????????????????????????????????????????????????????????????????????????????????? HTTP ?????????
        ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????? Amazon S3 ?????????????????????
    ?????? 2018 ??? 3 ??? 1 ?????????????????????????????????????????????????????????????????????????????????????????????????????? 255 ???????????????????????????????????????????????????
        ??? 2018 ??? 3 ??? 1 ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????

    ???????????????????????????????????????????????????????????????????????????
        docexamplebucket1
        log-delivery-march-2020
        my-hosted-content

    ??????????????????????????????????????????????????????????????????????????????????????????????????????
        docexamplewebsite.com
        www.docexamplewebsite.com
        my.example.s3.bucket

    ????????????????????????????????????
        doc_example_bucket?????????????????????
        DocExampleBucket????????????????????????
        doc-example-bucket-????????????????????????
    """

    @pytest.mark.ess
    def test_bucket_create_naming_bad_starts_non_alpha(self, s3cfg_global_unique):
        """
        ??????-?????? bucket name begins with underscore;
        400, InvalidBucketName
        """
        bucket_name = self.get_new_bucket_name(s3cfg_global_unique)
        self.check_bad_bucket_name(s3cfg_global_unique, '_' + bucket_name)

    @pytest.mark.ess
    def test_bucket_create_naming_bad_short_one(self, s3cfg_global_unique):
        """
        ??????-??????bucket name: short (one character) name;
        400, InvalidBucketName
        """
        self.check_bad_bucket_name(s3cfg_global_unique, 'a')

    @pytest.mark.ess
    def test_bucket_create_naming_bad_short_two(self, s3cfg_global_unique):
        """
        ??????-??????bucket name: short (two character) name;
        400, InvalidBucketName
        """
        self.check_bad_bucket_name(s3cfg_global_unique, 'aa')

    @pytest.mark.ess
    def test_bucket_create_naming_bad_ip(self, s3cfg_global_unique):
        """
        ??????-??????bucket name: create ip address for name;
        400, InvalidBucketName
        """
        self.check_bad_bucket_name(s3cfg_global_unique, '192.168.5.123')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="??????????????????????????????????????????", run=True, strict=True)
    def test_bucket_create_naming_bad_short_empty(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????????????????
        405???MethodNotAllowed
        """
        invalid_bucket_name = ''
        self.check_bad_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        # status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        # self.eq(status, 405)
        # self.eq(error_code, 'MethodNotAllowed')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="??????????????????3~63?????????255", run=True, strict=True)
    def test_bucket_create_naming_bad_long(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????
        ????????????????????????3~63?????????255
        """
        invalid_bucket_name = 256 * 'a'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)

        invalid_bucket_name = 280 * 'a'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)

        invalid_bucket_name = 3000 * 'a'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="?????????[a-zA-Z0-9._-]???Ceph??????????????????", run=True, strict=True)
    def test_bucket_create_naming_bad_punctuation(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????????????????
        """
        # Bucket name must match the regex "^[a-zA-Z0-9.\-_]{1,255}$"
        # or be an ARN matching the regex "^arn:(aws).*:(s3|s3-object-lambda):[a-z\-0-9]*:[0-9]{12}:accesspoint[/:][a-zA-Z0-9\-.
        # ]{1,63}$|^arn:(aws).*:s3-outposts:[a-z\-0-9]+:[0-9]{12}:outpost[/:][a-zA-Z0-9\-]{1,63}[/:]accesspoint[/:][a-zA-Z0-9\-]{1,63}$"

        # characters other than [a-zA-Z0-9._-]
        invalid_bucket_name = 'alpha!soup'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        print(status, error_code)
        # TODO: figure out why a 403 is coming out in boto3 but not in boto2.
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="?????????????????????????????????Ceph?????????", run=True, strict=True)
    def test_bucket_create_naming_dns_underscore(self, s3cfg_global_unique):
        """
        ??????-?????????????????????????????????????????????(ceph??????????????????)
        400???InvalidBucketName
        """
        invalid_bucket_name = 'foo_bar'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="???????????????????????????????????????Ceph?????????", run=True, strict=True)
    def test_bucket_create_naming_dns_dash_at_end(self, s3cfg_global_unique):
        """
        ??????-?????????????????????????????????????????????(ceph??????????????????)
        400???InvalidBucketName
        """
        invalid_bucket_name = 'foo-'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="??????????????????????????????????????????Ceph?????????", run=True, strict=True)
    def test_bucket_create_naming_dns_dot_dot(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????????????????????????????(ceph??????????????????)
        400???InvalidBucketName
        """
        invalid_bucket_name = 'foo..bar'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess_maybe
    @pytest.mark.fails_on_ess
    @pytest.mark.xfail(reason="?????????????????????????????????????????????????????????Ceph?????????", run=True, strict=True)
    def test_bucket_create_naming_dns_dash_dot(self, s3cfg_global_unique):
        """
        ??????-????????????????????????????????????????????????????????????(ceph??????????????????)
        400???InvalidBucketName
        """
        invalid_bucket_name = 'foo-.bar'
        status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        self.eq(status, 400)
        self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess
    def test_bucket_create_naming_dns_dot_dash(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????????????????????????????????????????(ceph??????????????????)
        """
        # ?????????????????????????????????????????????????????? (.) ???????????? (-) ?????????
        good_bucket_name = 'foo.-bar'
        self.check_good_bucket_name(s3cfg_global_unique, good_bucket_name)

        # invalid_bucket_name = 'foo.-bar'
        # status, error_code = self.check_invalid_bucket_name(s3cfg_global_unique, invalid_bucket_name)
        # self.eq(status, 400)
        # self.eq(error_code, 'InvalidBucketName')

    @pytest.mark.ess
    def test_bucket_create_naming_dns_long(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????63?????????(ceph?????????3~63??????????????????)???
        """
        prefix = s3cfg_global_unique.bucket_prefix
        assert len(prefix) < 50
        num = 63 - len(prefix)
        self.check_good_bucket_name(s3cfg_global_unique, num * 'a')

    @pytest.mark.ess
    def test_bucket_create_naming_good_starts_alpha(self, s3cfg_global_unique):
        """
        ??????-?????????????????????????????????(ceph??????????????????)???
        """
        # this test goes outside the user-configure prefix because it needs to
        # control the initial character of the bucket name
        client = get_client(s3cfg_global_unique)
        prefix = 'a' + s3cfg_global_unique.bucket_prefix
        nuke_prefixed_buckets(client, prefix)
        self.check_good_bucket_name(config=s3cfg_global_unique, name='foo', prefix=prefix)
        nuke_prefixed_buckets(client, prefix)

    @pytest.mark.ess
    def test_bucket_create_naming_good_starts_digit(self, s3cfg_global_unique):
        """
        ??????-?????????????????????????????????(ceph??????????????????)
        """
        # this test goes outside the user-configure prefix because it needs to
        # control the initial character of the bucket name
        client = get_client(s3cfg_global_unique)
        prefix = '0' + s3cfg_global_unique.bucket_prefix
        nuke_prefixed_buckets(client, prefix)
        self.check_good_bucket_name(config=s3cfg_global_unique, name='foo', prefix=prefix)
        nuke_prefixed_buckets(client, prefix)

    @pytest.mark.ess
    def test_bucket_create_naming_good_contains_period(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????????????????(ceph??????????????????)
        """
        self.check_good_bucket_name(s3cfg_global_unique, 'aaa.111')

    @pytest.mark.ess
    def test_bucket_create_naming_good_contains_hyphen(self, s3cfg_global_unique):
        """
        ??????-??????????????????????????????????????????(ceph??????????????????)
        """
        self.check_good_bucket_name(s3cfg_global_unique, 'aaa-111')

    @pytest.mark.ess
    def test_bucket_create_naming_good_long_60(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????60?????????(ceph????????????255)
        """
        self.bucket_create_naming_good_long(s3cfg_global_unique, 60)

    @pytest.mark.ess
    def test_bucket_create_naming_good_long_61(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????61?????????(ceph????????????255)
        """
        self.bucket_create_naming_good_long(s3cfg_global_unique, 61)

    @pytest.mark.ess
    def test_bucket_create_naming_good_long_62(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????62?????????(ceph????????????255)
        """
        self.bucket_create_naming_good_long(s3cfg_global_unique, 62)

    @pytest.mark.ess
    def test_bucket_create_naming_good_long_63(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????63?????????(ceph????????????255)
        """
        self.bucket_create_naming_good_long(s3cfg_global_unique, 63)

    @pytest.mark.ess
    def test_bucket_list_long_name(self, s3cfg_global_unique):
        """
        ??????-???????????????????????????61?????????(ceph????????????255)????????????????????????
        """
        prefix = self.get_new_bucket_name(s3cfg_global_unique)
        length = 61
        num = length - len(prefix)
        name = num * 'a'

        bucket_name = '{prefix}{name}'.format(
            prefix=prefix,
            name=name,
        )
        bucket = self.get_new_bucket_resource(s3cfg_global_unique, name=bucket_name)
        is_empty = self.bucket_is_empty(bucket)
        self.eq(is_empty, True)
